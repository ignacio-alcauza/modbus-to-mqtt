#!/usr/bin/env python3
"""
Deye Inverter Probe — Lee todos los registros y los muestra en pantalla.
Incluye dump raw de rangos clave para verificar direcciones.

Uso:
    cd /Users/nacho/Documents/dev/modbus-to-mqtt
    python3 src/deye_probe.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from devices.deye import DeyeInverterClient, DEYE_HYBRID_REGISTERS
from utils.modbus import BaseModbusClient

DEYE_IP   = '192.168.1.133'
DEYE_PORT = 502
DEYE_UNIT = 1

RST = '\033[0m'; B = '\033[1m'; DIM = '\033[2m'
BLU = '\033[94m'; GRN = '\033[92m'; YEL = '\033[93m'
CYN = '\033[96m'; RED = '\033[91m'; MAG = '\033[95m'; WHT = '\033[97m'


def hdr(title, color=BLU):
    print(f"\n  {color}{'═'*78}{RST}")
    print(f"  {color}║{RST}  {B}{title}{RST}")
    print(f"  {color}{'═'*78}{RST}")

def sec(title):
    print(f"\n  {DIM}{'─'*74}{RST}")
    print(f"  {CYN}{B}{title}{RST}")
    print(f"  {DIM}{'─'*74}{RST}")

def val(key, value, unit=''):
    u = f" {DIM}{unit}{RST}" if unit else ""
    print(f"    {WHT}{key}{RST}{'.'*(46-len(str(key)))} {GRN}{value}{RST}{u}")

def dump_range(client, start, count, label):
    """Dump raw registers in a range."""
    regs = client.read_holding_registers(start, count)
    if not regs:
        print(f"  {RED}ERROR leyendo {label} @ {start} (0x{start:04X}){RST}")
        return {}
    mem = {start + i: v for i, v in enumerate(regs)}

    print(f"\n  {B}{CYN}{'─'*70}{RST}")
    print(f"  {B}{label}{RST}  {DIM}(addr {start}–{start+count-1} / 0x{start:04X}–0x{start+count-1:04X}){RST}")
    print(f"  {DIM}{'─'*70}{RST}")
    print(f"  {'Addr':>8}  {'Dec':>7}  {'Hex':>6}  {'÷10':>9}  {'÷100':>9}")

    for addr, v in mem.items():
        signed = v - 0x10000 if v >= 0x8000 else v
        print(f"  {DIM}0x{addr:04X} ({addr:4d})  {v:7d}  0x{v:04X}  {v/10:>9.2f}  {v/100:>9.3f}  "
              f"{'← signed: '+str(signed) if signed != v else ''}{RST}")
    return mem


def main():
    print(f"\n{B}{BLU}{'='*80}{RST}")
    print(f"  {B}Deye Inverter Probe — SUN-6K-SG05LP1-EU-AM2-P{RST}")
    print(f"  {DIM}{DEYE_IP}:{DEYE_PORT} · Unit {DEYE_UNIT}{RST}")
    print(f"{B}{BLU}{'='*80}{RST}")

    # ── 1. Decoded values via existing client ──────────────────────────────────
    hdr("Valores decodificados (implementación actual)", GRN)
    client = DeyeInverterClient(host=DEYE_IP, port=DEYE_PORT, unit_id=DEYE_UNIT,
                                model='SUN-6K-SG05LP1-EU-AM2-P')
    try:
        with client:
            data = client.get_all_data()
            data.pop('_raw_data', None)

            sec("Identificación")
            for k in ['MODEL', 'DEVICE_TYPE', 'DEVICE_SERIAL']:
                if k in data:
                    val(k, data[k])

            sec("Energía acumulada (kWh)")
            for k in ['DAY_PV_ENERGY', 'TOTAL_PV_ENERGY',
                      'TOTAL_BATTERY_CHARGE', 'TOTAL_BATTERY_DISCHARGE',
                      'DAY_GRID_BUY', 'DAY_GRID_SELL',
                      'TOTAL_GRID_BUY', 'TOTAL_GRID_SELL',
                      'TOTAL_LOAD_ENERGY']:
                if k in data:
                    val(k, data[k], 'kWh')

            sec("Red eléctrica")
            for k in ['GRID_FREQUENCY', 'GRID_L1_VOLTAGE',
                      'GRID_L1_POWER', 'GRID_TOTAL_POWER']:
                if k in data:
                    unit = {'GRID_FREQUENCY': 'Hz', 'GRID_L1_VOLTAGE': 'V'}.get(k, 'W')
                    val(k, data[k], unit)

            sec("Carga")
            for k in ['LOAD_L1_POWER', 'LOAD_TOTAL_POWER']:
                if k in data:
                    val(k, data[k], 'W')

            sec("PV Solar")
            for k in ['PV1_VOLTAGE', 'PV1_CURRENT', 'PV1_POWER', 'PV2_POWER']:
                if k in data:
                    unit = {'PV1_VOLTAGE': 'V', 'PV1_CURRENT': 'A'}.get(k, 'W')
                    val(k, data[k], unit)

            sec("Batería")
            for k in ['BATTERY_TEMP', 'BATTERY_VOLTAGE', 'BATTERY_SOC',
                      'BATTERY_POWER', 'BATTERY_CURRENT']:
                if k in data:
                    unit = {'BATTERY_TEMP': '°C', 'BATTERY_VOLTAGE': 'V',
                            'BATTERY_SOC': '%', 'BATTERY_CURRENT': 'A'}.get(k, 'W')
                    val(k, data[k], unit)

            sec("Otros")
            for k in ['RADIATOR_TEMP']:
                if k in data:
                    val(k, data[k], '°C')

    except ConnectionError as e:
        print(f"\n  {RED}{B}ERROR conectando a {DEYE_IP}:{DEYE_PORT}{RST}\n  {e}")
        sys.exit(1)

    # ── 2. Raw dump de rangos clave ────────────────────────────────────────────
    hdr("Dump RAW de registros (para verificar direcciones)", YEL)
    raw_client = BaseModbusClient(host=DEYE_IP, port=DEYE_PORT, unit_id=DEYE_UNIT)
    try:
        with raw_client:
            dump_range(raw_client,   0, 10,  "Identificación (0–9)")
            dump_range(raw_client,  60, 41,  "Energía (60–100)")
            dump_range(raw_client, 100, 55,  "Live Data 1 (100–154)")
            dump_range(raw_client, 155, 50,  "Live Data 2 (155–204)")
    except ConnectionError as e:
        print(f"\n  {RED}ERROR en dump raw: {e}{RST}")

    print(f"\n{B}{BLU}{'='*80}{RST}")
    print(f"  {B}✓ Probe completado{RST}")
    print(f"{B}{BLU}{'='*80}{RST}\n")


if __name__ == '__main__':
    main()
