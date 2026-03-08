#!/usr/bin/env python3
import time
import argparse
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

def scan_registers(host, port, unit_id, register_type, start_addr, end_addr, batch_size=10):
    client = ModbusTcpClient(host=host, port=port, timeout=3)
    if not client.connect():
        print(f"Failed to connect to {host}:{port}")
        return

    print(f"\nScanning {register_type} registers from {start_addr} to {end_addr} (Unit ID: {unit_id})...")
    
    found_data = {}
    
    for base_addr in range(start_addr, end_addr, batch_size):
        try:
            if register_type == 'holding':
                result = client.read_holding_registers(address=base_addr, count=batch_size, slave=unit_id)
            else:
                result = client.read_input_registers(address=base_addr, count=batch_size, slave=unit_id)
                
            if not result.isError():
                for i, val in enumerate(result.registers):
                    addr = base_addr + i
                    found_data[addr] = val
            else:
                # Try reading one by one if batch fails
                for i in range(batch_size):
                    addr = base_addr + i
                    try:
                        if register_type == 'holding':
                            r = client.read_holding_registers(address=addr, count=1, slave=unit_id)
                        else:
                            r = client.read_input_registers(address=addr, count=1, slave=unit_id)
                        if not r.isError():
                            found_data[addr] = r.registers[0]
                    except:
                        pass
        except Exception as e:
            pass
            
        time.sleep(0.05)
        
    client.close()
    
    # Print results
    print(f"\n--- {register_type.upper()} REGISTERS ---")
    if not found_data:
        print("No readable registers found or all errors.")
    else:
        for addr in sorted(found_data.keys()):
            val = found_data[addr]
            print(f"Register {addr:04d} (0x{addr:04X}): {val:5d}  |  Hex: 0x{val:04X}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.1.136")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--unit-id", type=int, default=1)
    args = parser.parse_args()
    
    scan_registers(args.host, args.port, args.unit_id, 'holding', 0, 300, batch_size=10)
    scan_registers(args.host, args.port, args.unit_id, 'input', 0, 300, batch_size=10)
