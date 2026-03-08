#!/usr/bin/env python3
import time
from pymodbus.client import ModbusTcpClient

def probe_registers(host, port, unit):
    client = ModbusTcpClient(host, port=port, timeout=3)
    if not client.connect():
        print("Failed to connect!")
        return
        
    def read_addr(addr, count=5):
        try:
            r = client.read_holding_registers(addr, count=count, slave=unit)
            if not r.isError():
                print(f"Holding @0x{addr:04X}: {[hex(x) for x in r.registers]}")
            else:
                print(f"Holding @0x{addr:04X}: ERROR")
        except Exception as e:
            print(f"Holding @0x{addr:04X}: EXC {e}")
            
        try:
            r2 = client.read_input_registers(addr, count=count, slave=unit)
            if not r2.isError():
                print(f"Input   @0x{addr:04X}: {[hex(x) for x in r2.registers]}")
            else:
                print(f"Input   @0x{addr:04X}: ERROR")
        except Exception as e:
            print(f"Input   @0x{addr:04X}: EXC {e}")

    print("Probing 0x0000 base...")
    read_addr(0x0000)
    read_addr(0x0090) # BatVol
    print("Probing 0x1200 base...")
    read_addr(0x1200)
    read_addr(0x1290) # BatVol
    
    client.close()

if __name__ == '__main__':
    probe_registers('192.168.1.136', 502, 1)
