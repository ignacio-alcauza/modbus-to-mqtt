#!/usr/bin/env python3
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.136', port=502, timeout=3)
client.connect()

def r(addr, count=10):
    res = client.read_holding_registers(addr, count=count, slave=1)
    if not res.isError():
        print(f"{addr:04X}: {[hex(x) for x in res.registers]}")
    else:
        print(f"{addr:04X}: ERROR")

r(0x1200, 10)
r(0x1248, 5)
r(0x1290, 5)
r(0x1298, 5) # Current
r(0x12A4, 5) # BalanCurrent
r(0x12A8, 5) # SOC Cap Remain

client.close()
