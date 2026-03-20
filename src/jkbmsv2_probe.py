#!/usr/bin/env python3
"""
JK BMS V2 Probe — Lee TODOS los registros del mapa V1.1 y los muestra en pantalla.

Uso:
    cd /Users/nacho/Documents/dev/modbus-to-mqtt
    python src/jkbmsv2_probe.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from devices.jkbmsv2 import (
    JKBMSV2Client,
    CONFIG_REGISTERS,
    REALTIME_REGISTERS,
    DEVICE_INFO_REGISTERS,
    format_uptime,
)

BMS_IP = '192.168.1.136'
BMS_PORT = 502
BMS_UNIT = 1

# ─── Colores ANSI ──────────────────────────────────────────────────────────────
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

def val(key, value, unit='', desc=''):
    u = f" {DIM}{unit}{RST}" if unit else ""
    d = f"  {DIM}// {desc}{RST}" if desc else ""
    print(f"    {WHT}{key}{RST}{'.'*(48-len(key))} {GRN}{value}{RST}{u}{d}")

def arr(key, values, unit='', per_row=8):
    print(f"    {WHT}{key}{RST}  {DIM}({len(values)} items, {unit}){RST}")
    for i in range(0, len(values), per_row):
        chunk = values[i:i+per_row]
        labels = '  '.join(f"{DIM}{f'[{i+j:2d}]':>8s}{RST}" for j in range(len(chunk)))
        items  = '  '.join(f"{GRN}{v:>8}{RST}" for v in chunk)
        print(f"      {labels}")
        print(f"      {items}")


def main():
    print(f"\n{B}{BLU}{'='*80}{RST}")
    print(f"  {B}JK BMS V2 Probe — Mapa completo V1.1 (FW v27){RST}")
    print(f"  {DIM}JK-PB2A16S20P HW v19 · {BMS_IP}:{BMS_PORT} · Unit {BMS_UNIT}{RST}")
    print(f"{B}{BLU}{'='*80}{RST}")

    client = JKBMSV2Client(host=BMS_IP, port=BMS_PORT, unit_id=BMS_UNIT)

    try:
        with client:
            # ═══ BLOQUE 0x1400 — Info Dispositivo ═══
            hdr("BLOQUE 0x1400 — Información del dispositivo", YEL)
            try:
                di = client.read_device_info_block()
                if di:
                    for k, reg in DEVICE_INFO_REGISTERS.items():
                        v = di.get(k)
                        if v is not None:
                            val(k, v, reg.get('unit', ''), reg.get('desc', ''))
                    if 'ODD_RUN_TIME_TEXT' in di:
                        val('ODD_RUN_TIME_TEXT', di['ODD_RUN_TIME_TEXT'], '', 'Formato legible')
                else:
                    print(f"    {RED}No se pudo leer el bloque 0x1400{RST}")
            except Exception as e:
                print(f"    {RED}Error: {e}{RST}")

            # ═══ BLOQUE 0x1200 — Datos en tiempo real ═══
            hdr("BLOQUE 0x1200 — Datos en tiempo real", GRN)
            try:
                rt = client.read_realtime_block()
                if rt:
                    # Voltajes de celdas
                    if 'CELL_VOLTAGES' in rt:
                        sec("Voltajes de celdas (mV)")
                        arr('CELL_VOLTAGES', rt['CELL_VOLTAGES'], 'mV')

                    # Resistencias
                    if 'CELL_RESISTANCES' in rt:
                        sec("Resistencias de celdas (mΩ)")
                        arr('CELL_RESISTANCES', rt['CELL_RESISTANCES'], 'mΩ')

                    # Estadísticas de celdas
                    sec("Estadísticas de celdas")
                    for k in ['CELL_VOL_AVE', 'CELL_VDIF_MAX', 'MAX_VOL_CELL_NBR', 'MIN_VOL_CELL_NBR']:
                        if k in rt:
                            reg = REALTIME_REGISTERS.get(k, {})
                            val(k, rt[k], reg.get('unit', ''), reg.get('desc', ''))

                    # Temperaturas
                    sec("Temperaturas")
                    for k in ['TEMP_MOS', 'TEMP_BAT1', 'TEMP_BAT2', 'TEMP_BAT3']:
                        if k in rt:
                            reg = REALTIME_REGISTERS.get(k, {})
                            v = rt[k]
                            val(k, f"{v}°C", '', reg.get('desc', ''))

                    # Pack
                    sec("Pack — Voltaje / Corriente / Potencia")
                    if 'BAT_VOL' in rt:
                        val('BAT_VOL', f"{rt['BAT_VOL']} V", '', 'Voltaje total')
                    if 'BAT_CURRENT' in rt:
                        val('BAT_CURRENT', f"{rt['BAT_CURRENT']} A", '', 'Corriente (+carga, -descarga)')
                    if 'BAT_POWER_W' in rt:
                        val('BAT_POWER_W', f"{rt['BAT_POWER_W']} W", '', 'Potencia V×I')
                    if 'CHARGING_POWER' in rt:
                        val('CHARGING_POWER', f"{rt['CHARGING_POWER']} W", '', '')
                    if 'DISCHARGING_POWER' in rt:
                        val('DISCHARGING_POWER', f"{rt['DISCHARGING_POWER']} W", '', '')

                    # SOC / Capacidad
                    sec("SOC / Capacidad / Ciclos")
                    for k in ['SOC', 'SOC_CAP_REMAIN', 'SOC_FULL_CHARGE_CAP', 'SOC_CYCLE_COUNT', 'SOC_CYCLE_CAP']:
                        if k in rt:
                            reg = REALTIME_REGISTERS.get(k, {})
                            val(k, rt[k], reg.get('unit', ''), reg.get('desc', ''))

                    # Balanceo
                    sec("Balanceo")
                    for k in ['BALAN_CURRENT', 'BALAN_STA', 'BALAN_STA_TEXT']:
                        if k in rt:
                            reg = REALTIME_REGISTERS.get(k, {})
                            val(k, rt[k], reg.get('unit', ''), reg.get('desc', ''))

                    # Estado Carga/Descarga — deshabilitado (0x12B8 no confirmado)


                    # Alarmas
                    sec("Alarmas")
                    if 'ALARMS' in rt:
                        val('ALARMS (raw)', f"0x{int(rt['ALARMS']):08X}", '', '')
                    if 'ALARMS_DECODED' in rt:
                        for a in rt['ALARMS_DECODED']:
                            color = RED if a != 'Normal' else GRN
                            print(f"      {color}● {a}{RST}")

                    # Runtime
                    sec("Runtime")
                    for k in ['RUNTIME', 'RUNTIME_TEXT', 'SYS_RUN_TICKS', 'RTC_TICKS']:
                        if k in rt:
                            reg = REALTIME_REGISTERS.get(k, {})
                            val(k, rt[k], reg.get('unit', ''), reg.get('desc', ''))

                    # Recovery timers (solo si > 0)
                    active_timers = {k: rt[k] for k in ['TIME_DC_OCPR', 'TIME_DC_SCPR', 'TIME_COCPR', 'TIME_UVPR', 'TIME_OVPR'] if k in rt and rt[k] > 0}
                    if active_timers:
                        sec("Tiempos de recuperación ACTIVOS")
                        for k, v in active_timers.items():
                            val(k, v, 's', REALTIME_REGISTERS.get(k, {}).get('desc', ''))
                else:
                    print(f"    {RED}No se pudo leer el bloque 0x1200{RST}")
            except Exception as e:
                import traceback
                print(f"    {RED}Error: {e}{RST}")
                traceback.print_exc()

            # ═══ BLOQUE 0x1000 — Configuración ═══
            hdr("BLOQUE 0x1000 — Configuración (R/W)", MAG)
            try:
                cfg = client.read_config_block()
                if cfg:
                    sec("Protecciones de voltaje")
                    for k in [k for k in CONFIG_REGISTERS if k.startswith('VOL_')]:
                        if k in cfg:
                            reg = CONFIG_REGISTERS[k]
                            v = cfg[k]
                            extra = f" → {v/1000:.3f} V" if reg.get('unit') == 'mV' else ''
                            val(k, f"{v}{extra}", reg.get('unit', ''), reg.get('desc', ''))

                    sec("Protecciones de corriente")
                    for k in [k for k in CONFIG_REGISTERS if k.startswith('CUR_')]:
                        if k in cfg:
                            reg = CONFIG_REGISTERS[k]
                            v = cfg[k]
                            extra = f" → {v/1000:.3f} A" if reg.get('unit') == 'mA' else ''
                            val(k, f"{v}{extra}", reg.get('unit', ''), reg.get('desc', ''))

                    sec("Protecciones de temperatura")
                    for k in [k for k in CONFIG_REGISTERS if k.startswith('TMP_')]:
                        if k in cfg:
                            reg = CONFIG_REGISTERS[k]
                            v = cfg[k]
                            if reg.get('scale') == 0.1:
                                val(k, f"{v}°C", '', reg.get('desc', ''))
                            else:
                                val(k, v, reg.get('unit', ''), reg.get('desc', ''))

                    sec("Tiempos / Retardos")
                    for k in [k for k in CONFIG_REGISTERS if k.startswith('TIM_')]:
                        if k in cfg:
                            reg = CONFIG_REGISTERS[k]
                            val(k, cfg[k], reg.get('unit', ''), reg.get('desc', ''))

                    sec("Switches")
                    for k in ['BAT_CHARGE_EN', 'BAT_DISCHARGE_EN', 'BALAN_EN']:
                        if k in cfg:
                            v = cfg[k]
                            text = 'ON' if v else 'OFF'
                            val(k, f"{v} ({text})", '', CONFIG_REGISTERS[k].get('desc', ''))

                    sec("Otros parámetros")
                    for k in ['CELL_COUNT', 'CAP_BAT_CELL', 'SCP_DELAY', 'DEV_ADDR', 'CONFIG_FLAGS']:
                        if k in cfg:
                            reg = CONFIG_REGISTERS[k]
                            v = cfg[k]
                            if k == 'CAP_BAT_CELL':
                                v = f"{v} mAh → {v/1000:.3f} Ah"
                            elif k == 'CONFIG_FLAGS':
                                v = f"0x{v:04X}"
                            val(k, v, reg.get('unit', ''), reg.get('desc', ''))

                    if 'CONFIG_FLAGS_DECODED' in cfg:
                        sec("Flags de configuración")
                        for flag_name, active in cfg['CONFIG_FLAGS_DECODED'].items():
                            color = GRN if active else DIM
                            sym = '●' if active else '○'
                            print(f"      {color}{sym} {flag_name}{RST}")

                    if 'CELL_CON_WIRE_RES' in cfg:
                        sec("Resistencias de cableado (µΩ)")
                        arr('CELL_CON_WIRE_RES', cfg['CELL_CON_WIRE_RES'], 'µΩ')
                else:
                    print(f"    {RED}No se pudo leer el bloque 0x1000{RST}")
            except Exception as e:
                import traceback
                print(f"    {RED}Error: {e}{RST}")
                traceback.print_exc()

    except ConnectionError as e:
        print(f"\n  {RED}{B}ERROR: No se pudo conectar en {BMS_IP}:{BMS_PORT}{RST}")
        print(f"  {RED}{e}{RST}")
        sys.exit(1)

    print(f"\n{B}{BLU}{'='*80}{RST}")
    print(f"  {B}✓ Lectura completada{RST}")
    print(f"{B}{BLU}{'='*80}{RST}\n")


if __name__ == '__main__':
    main()
