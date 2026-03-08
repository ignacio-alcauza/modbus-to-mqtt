#!/usr/bin/env python3
import time
import argparse
from pymodbus.client import ModbusTcpClient
try:
    from pymodbus.framer.rtu_framer import ModbusRtuFramer
    from pymodbus.framer.socket_framer import ModbusSocketFramer
except ImportError:
    from pymodbus.transaction import ModbusRtuFramer, ModbusSocketFramer

def scan_registers(host, port, unit_id, framer, register_type, start_addr, end_addr, batch_size=1):
    if framer == 'rtu':
        client = ModbusTcpClient(host=host, port=port, framer=ModbusRtuFramer, timeout=2)
    else:
        client = ModbusTcpClient(host=host, port=port, framer=ModbusSocketFramer, timeout=2)
        
    if not client.connect():
        print(f"Failed to connect to {host}:{port}")
        return

    print(f"\nScanning {register_type} registers {start_addr}-{end_addr} (Unit ID: {unit_id}, Framer: {framer})...")
    
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
        except Exception as e:
            pass
            
        time.sleep(0.02)
        
    client.close()
    
    if found_data:
        print(f"\n--- {register_type.upper()} REGISTERS (Framer: {framer}, Unit: {unit_id}) ---")
        for addr in sorted(found_data.keys()):
            val = found_data[addr]
            print(f"Register {addr:04d} (0x{addr:04X}): {val:5d}  |  Hex: 0x{val:04X}")
        return True
    return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.1.136")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--port2", type=int, default=8899)
    args = parser.parse_args()
    
    test_addrs = [0, 28, 48, 40000] # minimal check points
    
    success = False
    for port in [args.port, args.port2]:
        for framer in ['tcp', 'rtu']:
            for uid in [1, 0, 2, 255]:
                for reg_type in ['holding', 'input']:
                    for addr in test_addrs:
                        # Scan 10 registers around the test addr
                        if scan_registers(args.host, port, uid, framer, reg_type, addr, addr+5):
                            success = True
                            break
                    if success: break
                if success: break
            if success: break
        if success: break
    
    if success:
        print("Successfully found readable registers!")
    else:
        print("No readable registers found across all combinations.")
