#!/usr/bin/env python3
import socket
import time
import struct
import argparse

def chksum(data):
    checksum = 0
    for b in data:
        checksum += b
    return checksum

def build_read_all_frame():
    # Built based on ESPHome jk_modbus.cpp logic for JK PB2A16S20P
    frame = bytearray(21)
    frame[0] = 0x4E  # start
    frame[1] = 0x57  # start
    frame[2] = 0x00  # length low
    frame[3] = 0x13  # length high
    frame[4] = 0x00  # term
    frame[5] = 0x00
    frame[6] = 0x00
    frame[7] = 0x00
    frame[8] = 0x06  # FUNCTION_READ_ALL_REGISTERS
    frame[9] = 0x03  # frame source: computer
    frame[10] = 0x00 # frame type: read data
    frame[11] = 0x00 # register: read all
    frame[12] = 0x00 # record number
    frame[13] = 0x00
    frame[14] = 0x00
    frame[15] = 0x00
    frame[16] = 0x68 # end sequence
    
    crc = chksum(frame[:17])
    frame[17] = 0x00
    frame[18] = 0x00
    frame[19] = (crc >> 8) & 0xFF
    frame[20] = crc & 0xFF
    
    return frame

def scan_jk_bms(host, port):
    print(f"Connecting to {host}:{port} for JK BMS PB2A16S20P custom protocol scan...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((host, port))
        
        frame = build_read_all_frame()
        print(f"Sending frame: {frame.hex()}")
        s.sendall(frame)
        
        data = s.recv(4096)
        if not data:
            print("No data received.")
            return
            
        print(f"Received {len(data)} bytes: {data.hex()[:100]}...")
        
        if len(data) > 21 and data[0] == 0x4E and data[1] == 0x57:
            print("Valid header found!")
            # Attempt basic parsing
            data_len = (data[2] << 8) | data[3]
            print(f"Reported Data Length: {data_len}")
            
            if data_len > 11:
                # Based on typical JK BMS V1.1 replies, data payload starts around byte 11 or 14
                print("Parsing basic values (assuming standard JK offsets for V1.1)...")
                try:
                    # Very rough guess on offsets based on length, would need exact map for PB2A16S20P
                    # But if we get a response, the protocol works!
                    pass
                except Exception as e:
                    print(f"Parse partial error: {e}")
        else:
            print("Response does not look like a valid JK BMS frame.")
            
        s.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.1.136")
    parser.add_argument("--port", type=int, default=8899) # Often 8899 on Elfin, but try 502 as well
    args = parser.parse_args()
    
    scan_jk_bms(args.host, 502)
    time.sleep(1)
    scan_jk_bms(args.host, 8899)
