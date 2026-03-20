#!/usr/bin/env python3
"""
Probe script to locate missing JK BMS parameters:
  - balancing_current       (corriente de balanceo activo)
  - balance_trigger_voltage (voltaje umbral para activar balanceo)
  - balancer                (estado del balanceador, quizás diferente a BALANCE_STATUS)
  - total_charging_cycle_capacity (capacidad total acumulada por ciclos de carga)
  - SYS_STATUS              (verificar qué hay realmente en 0x12B8)

Known register map (confirmed):
  0x1200-0x120F  Cell voltages (16 x UINT16, mV)
  0x1222         Cell avg voltage
  0x1223         Cell volt diff
  0x1224         Cell max/min no
  0x1225-0x1234  Cell resistances (16 x UINT16, mΩ)
  0x1285         Temp MOS
  0x1289         Bat Voltage
  0x128C-0x128D  Bat Current (INT32)
  0x128E         Temp T1
  0x128F         Temp T2
  0x1293         SOC% (low byte) + Balance Status (high byte)
  0x1294-0x1295  SOC cap remain (UINT32)
  0x1296-0x1297  SOC full cap (UINT32)
  0x129C-0x129D  SYS_STATUS with CHARGE(bit14)/DISCHARGE(bit13) flags
  0x129E-0x129F  Uptime (UINT32)
  0x12A1-0x12A2  Alarms 32bit
  0x12B4-0x12B5  Total charged capacity (UINT32, mAh)
  0x12B6         Cycle count
  0x12B8-0x12B9  ??? (currently mapped as SYS_STATUS - suspect)
  0x12BC         Temp T3
  0x12BD         Temp T4
  0x12BE         Temp T5

Candidate addresses to investigate (from JK BMS documentation / reverse engineering):
  0x12A3-0x12A5  Possible balancing current area
  0x12A6-0x12AB  Unknown area
  0x12B0-0x12B3  Unknown area (could be balance trigger voltage, balancer state)
  0x12B7         Unknown single register between cycle count and unknown
  0x12B8-0x12B9  Currently SYS_STATUS - verify real content
  0x12BA-0x12BB  Unknown
"""

import struct
from pymodbus.client import ModbusTcpClient

BMS_IP = '192.168.1.136'
BMS_PORT = 502
BMS_UNIT = 1

def decode(regs, rtype='UINT16', scale=1.0):
    if not regs:
        return None
    if rtype == 'UINT16':
        return regs[0] * scale
    elif rtype == 'INT16':
        v = struct.unpack('>h', struct.pack('>H', regs[0]))[0]
        return v * scale
    elif rtype == 'UINT32':
        v = (regs[0] << 16) + regs[1]
        return v * scale
    elif rtype == 'UINT32_SWAP':
        v = (regs[1] << 16) + regs[0]
        return v * scale
    elif rtype == 'INT32':
        v = struct.unpack('>i', struct.pack('>I', (regs[0] << 16) + regs[1]))[0]
        return v * scale
    elif rtype == 'FLOAT32':
        v = struct.unpack('>f', struct.pack('>HH', regs[0], regs[1]))[0]
        return v
    elif rtype == 'FLOAT32_SWAP':
        v = struct.unpack('>f', struct.pack('>HH', regs[1], regs[0]))[0]
        return v
    return regs[0] * scale

client = ModbusTcpClient(BMS_IP, port=BMS_PORT, timeout=5)
if not client.connect():
    print("ERROR: No se pudo conectar al BMS")
    exit(1)

print(f"\n{'='*70}")
print(f"  JK BMS Missing Parameters Probe  —  {BMS_IP}:{BMS_PORT}")
print(f"{'='*70}\n")

def read_block(start, count=64):
    r = client.read_holding_registers(start, count=count, slave=BMS_UNIT)
    if r.isError():
        print(f"ERROR leyendo bloque 0x{start:04X}")
        return []
    return r.registers

# Read the full monitored block (already known)
print("▶ Leyendo bloque completo 0x1200-0x12BF (3x64 registros)...")
block = []
for start in [0x1200, 0x1240, 0x1280]:
    chunk = read_block(start, 64)
    block.extend(chunk if chunk else [0]*64)
print(f"  Total registros leídos: {len(block)}\n")

def blk(addr, count=1):
    offset = addr - 0x1200
    if offset < 0 or offset + count > len(block):
        return None
    return block[offset:offset+count]

# ─── AREA DE INVESTIGACION ─────────────────────────────────────────────────

print("─" * 70)
print("ZONA 1: 0x12A0-0x12B3 — área sospechosa (entre alarms y total_chg)")
print("─" * 70)
for addr in range(0x12A0, 0x12B4):
    regs = blk(addr, 2)
    if regs:
        r0, r1 = regs[0], regs[1]
        as_uint16 = r0
        as_int16 = struct.unpack('>h', struct.pack('>H', r0))[0]
        as_uint32 = (r0 << 16) + r1
        as_int32 = struct.unpack('>i', struct.pack('>I', (r0 << 16) + r1))[0]
        as_float = struct.unpack('>f', struct.pack('>HH', r0, r1))[0]
        print(f"  0x{addr:04X}: raw=[0x{r0:04X}, 0x{r1:04X}]  "
              f"u16={as_uint16}  i16={as_int16}  "
              f"u32={as_uint32}  i32={as_int32}  "
              f"f32={as_float:.4f}")

print()
print("─" * 70)
print("ZONA 2: 0x12B4-0x12BF — total_chg_capacity, cycles, SYS_STATUS, temps")
print("─" * 70)
for addr in range(0x12B4, 0x12C0):
    regs = blk(addr, 2)
    if regs:
        r0, r1 = regs[0], regs[1]
        as_uint16 = r0
        as_int16 = struct.unpack('>h', struct.pack('>H', r0))[0]
        as_uint32 = (r0 << 16) + r1
        as_float = struct.unpack('>f', struct.pack('>HH', r0, r1))[0]
        print(f"  0x{addr:04X}: raw=[0x{r0:04X}, 0x{r1:04X}]  "
              f"u16={as_uint16}  i16={as_int16}  "
              f"u32={as_uint32}  f32={as_float:.4f}")

print()
print("─" * 70)
print("ZONA 3: CANDIDATOS ESPECÍFICOS — interpretación semántica")
print("─" * 70)

# 0x12A3-0x12A4: posible balancing current (INT16 o UINT32?)
r12A3 = blk(0x12A3, 2)
if r12A3:
    v_i16 = struct.unpack('>h', struct.pack('>H', r12A3[0]))[0]
    v_u32 = (r12A3[0] << 16) + r12A3[1]
    print(f"  0x12A3 como balancing_current (INT16 × 0.001 A): {v_i16 * 0.001:.3f} A")
    print(f"  0x12A3 como balancing_current (UINT32 × 0.001 A): {v_u32 * 0.001:.3f} A")

# 0x12A5: posible balance trigger voltage  
r12A5 = blk(0x12A5, 2)
if r12A5:
    print(f"  0x12A5 como balance_trigger_voltage (UINT16 × 0.001 V): {r12A5[0] * 0.001:.3f} V")
    print(f"  0x12A6 raw: 0x{r12A5[1]:04X} = {r12A5[1]}")

# 0x12B2-0x12B3: posible balance trigger area
r12B2 = blk(0x12B2, 2)
if r12B2:
    print(f"  0x12B2 como balance_trigger_voltage (UINT16 × 0.001 V): {r12B2[0] * 0.001:.3f} V")
    print(f"  0x12B3 raw: 0x{r12B2[1]:04X} = {r12B2[1]}")

# 0x12B7: registro entre cycle_count y sys_status (actualmente desconocido)
r12B7 = blk(0x12B7, 2)
if r12B7:
    print(f"  0x12B7 (unknown): raw=0x{r12B7[0]:04X} = {r12B7[0]} (posible balancer flag?)")

# 0x12B8-0x12B9: actualmente SYS_STATUS — qué es realmente?
r12B8 = blk(0x12B8, 2)
if r12B8:
    v_u32 = (r12B8[0] << 16) + r12B8[1]
    v_u32_swap = (r12B8[1] << 16) + r12B8[0]
    v_float = struct.unpack('>f', struct.pack('>HH', r12B8[0], r12B8[1]))[0]
    v_float_swap = struct.unpack('>f', struct.pack('>HH', r12B8[1], r12B8[0]))[0]
    print(f"  0x12B8-12B9 (actual SYS_STATUS):")
    print(f"    raw = [0x{r12B8[0]:04X}, 0x{r12B8[1]:04X}]")
    print(f"    UINT32       = {v_u32} (0x{v_u32:08X})")
    print(f"    UINT32_SWAP  = {v_u32_swap} (0x{v_u32_swap:08X})")
    print(f"    FLOAT32      = {v_float:.4f}")
    print(f"    FLOAT32_SWAP = {v_float_swap:.4f}")
    print(f"    Como total_cycle_cap (UINT32 ×0.001 Ah): {v_u32 * 0.001:.3f} Ah")
    print(f"    Como total_cycle_cap (UINT32_SWAP ×0.001 Ah): {v_u32_swap * 0.001:.3f} Ah")

# 0x12BA-0x12BB: desconocido
r12BA = blk(0x12BA, 2)
if r12BA:
    v_u32 = (r12BA[0] << 16) + r12BA[1]
    print(f"  0x12BA-12BB: raw=[0x{r12BA[0]:04X}, 0x{r12BA[1]:04X}]  UINT32={v_u32}  ×0.001={v_u32*0.001:.3f}")

print()
print("─" * 70)
print("ZONA 4: LECTURA EXTENDIDA 0x12C0-0x12FF (fuera del bloque estándar)")
print("─" * 70)
ext_block = read_block(0x12C0, 64)
if ext_block:
    for i, val in enumerate(ext_block):
        addr = 0x12C0 + i
        as_i16 = struct.unpack('>h', struct.pack('>H', val))[0]
        print(f"  0x{addr:04X}: 0x{val:04X}  u16={val}  i16={as_i16}")

print()
print("─" * 70)
print("RESUMEN — valores actuales confirmados:")
print("─" * 70)

# Mostrar valores conocidos para referencia cruzada
r_soc = blk(0x1293, 1)
r_bat_vol = blk(0x1289, 1)
r_bat_cur = blk(0x128C, 2)
r_total_chg = blk(0x12B4, 2)
r_cycle = blk(0x12B6, 1)
r_status_32 = blk(0x129C, 2)

if r_soc:
    print(f"  SOC: {r_soc[0] & 0xFF}%  BalanceStatus_raw: {(r_soc[0] >> 8) & 0xFF}")
if r_bat_vol:
    print(f"  Bat Voltage: {r_bat_vol[0] * 0.001:.3f} V")
if r_bat_cur:
    cur = struct.unpack('>i', struct.pack('>I', (r_bat_cur[0] << 16) + r_bat_cur[1]))[0]
    print(f"  Bat Current: {cur * 0.001:.3f} A")
if r_total_chg:
    v = (r_total_chg[0] << 16) + r_total_chg[1]
    print(f"  Total Chg Capacity (UINT32 @ 0x12B4): {v * 0.001:.3f} Ah")
if r_cycle:
    print(f"  Cycle Count: {r_cycle[0]}")
if r_status_32:
    v = (r_status_32[1] << 16) + r_status_32[0]  # SWAP
    print(f"  SysStatus @0x129C (UINT32_SWAP): 0x{v:08X} = {v}")
    print(f"    Bit13 (discharge): {bool(v & (1<<13))}")
    print(f"    Bit14 (charge):    {bool(v & (1<<14))}")

client.close()
print(f"\n{'='*70}\n")
