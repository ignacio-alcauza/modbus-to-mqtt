import json
from devices.jkbms import JKBMSClient

client = JKBMSClient("192.168.1.136", 502, 1)
client.connect()

data = {}
for start in range(0x1100, 0x1500, 64):
    chunk = client.read_holding_registers(start, 64)
    if chunk:
        data[hex(start)] = chunk
    else:
        print(f"Failed to read block starting at {hex(start)}")

with open('logs/modbus_scan.json', 'w') as f:
    json.dump(data, f, indent=2)
print("Scan complete.")
