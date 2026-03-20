"""
JK BMS JK-PB2A16S20P  —  Mapa de registros completo V1.1 (HW v19, FW v27)
Protocolo: 001 · Baud rate: 115200
Función Modbus: 0x03 (read) / 0x10 (write multiple)

NOTA IMPORTANTE sobre direcciones:
- El documento V1.1 usa direcciones de BYTE (cada byte en memoria tiene una dirección).
- El firmware v27 expone la memoria como registros Modbus de 16 bits (words) pero
  NO divide las direcciones entre 2. Es decir, la dirección Modbus 0x1000 corresponde
  a los bytes en las posiciones de memoria 0x1000 y 0x1001.
- Para UINT32 (4 bytes), el BMS los almacena en 2 words Modbus consecutivos.
  Si el doc dice que UINT32 está en byte 0x1000, ocupa Modbus regs 0x1000 y 0x1001
  en el bloque 0x1000 (que parece usar stride=2 para UINT32).

- Sin embargo, el bloque 0x1200 (realtime) en FW v27 difiere significativamente
  del documento oficial. Las direcciones confirmadas por sondeo empírico se mantienen.

Este módulo usa DOS fuentes de verdad:
  1. Bloque 0x1000 (Config): direcciones del doc V1.1 (confirmadas por sondeo)
  2. Bloque 0x1200 (Realtime): direcciones confirmadas empíricamente para FW v27
  3. Bloque 0x1400 (Device Info): direcciones del doc V1.1
"""

import struct
import logging
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.jkbmsv2")


# ═══════════════════════════════════════════════════════════════════════════════
# Funciones de decodificación
# ═══════════════════════════════════════════════════════════════════════════════

def decode_register(raw_regs, reg_def):
    """Decodifica un registro desde lista de UINT16 raw."""
    rtype = reg_def.get('type', 'UINT16')
    if not raw_regs:
        return None

    if rtype == 'UINT16':
        return raw_regs[0]
    elif rtype == 'INT16':
        return struct.unpack('>h', struct.pack('>H', raw_regs[0]))[0]
    elif rtype == 'UINT32':
        if len(raw_regs) < 2:
            return None
        return (raw_regs[0] << 16) | raw_regs[1]
    elif rtype == 'INT32':
        if len(raw_regs) < 2:
            return None
        return struct.unpack('>i', struct.pack('>I', (raw_regs[0] << 16) | raw_regs[1]))[0]
    elif rtype == 'FLOAT32':
        if len(raw_regs) < 2:
            return None
        return round(struct.unpack('>f', struct.pack('>HH', raw_regs[0], raw_regs[1]))[0], 4)
    elif rtype == 'UINT8_HIGH':
        return (raw_regs[0] >> 8) & 0xFF
    elif rtype == 'UINT8_LOW':
        return raw_regs[0] & 0xFF
    elif rtype == 'ASCII':
        length = reg_def.get('length', 16)
        word_count = (length + 1) // 2
        if len(raw_regs) < word_count:
            return None
        raw_bytes = b''
        for w in raw_regs[:word_count]:
            raw_bytes += struct.pack('>H', w)
        return raw_bytes.decode('ascii', errors='replace').rstrip('\x00').strip()
    else:
        return raw_regs[0]


def words_needed(reg_def):
    """Cuántos registros Modbus (words 16-bit) necesita este registro."""
    rtype = reg_def.get('type', 'UINT16')
    if rtype in ('UINT32', 'INT32', 'FLOAT32'):
        return 2
    elif rtype == 'ASCII':
        return (reg_def.get('length', 16) + 1) // 2
    else:
        return 1


def format_uptime(seconds):
    """Formatea segundos en formato humano."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0s"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:     parts.append(f"{days}d")
    if hours:    parts.append(f"{hours}h")
    if minutes:  parts.append(f"{minutes}m")
    if secs or not parts: parts.append(f"{secs}s")
    return " ".join(parts)


def decode_alarms(alarm_value):
    """Decodifica bitmask de alarmas a lista de strings."""
    if not alarm_value:
        return ['Normal']
    alarms = [ALARM_BITS[b] for b in ALARM_BITS if (alarm_value >> b) & 1]
    return alarms if alarms else ['Normal']


def decode_config_flags(flag_value):
    """Decodifica bitmask de flags de configuración."""
    if not flag_value:
        return {}
    return {CONFIG_FLAG_BITS[b]: bool((flag_value >> b) & 1) for b in CONFIG_FLAG_BITS}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 0x1000 — Configuración (R/W)
# Las direcciones del doc V1.1 SÍ funcionan para este bloque.
# UINT32 ocupa 2 registros consecutivos (stride 2 en words).
# ═══════════════════════════════════════════════════════════════════════════════

# Nota: en el bloque config, el BMS mapea UINT32 en las posiciones de byte del doc
# divididas por 2. Así 0x1000 byte → reg 0x0800, 0x1004 → 0x0802, etc.
# PERO el primer sondeo muestra que usando las direcciones directas del doc (0x1000)
# sí da valores correctos (VOL_CELL_UV=3100, etc). Así que el BMS acepta direcciones
# de byte directamente.

CONFIG_REGISTERS = {
    # El stride en este bloque es 2 words por UINT32 (4 bytes).
    # addr aquí = la dirección del doc / 2  cuando hay discrepancia.
    # Pero si el doc funciona directo, usamos las del doc.
    'VOL_SMART_SLEEP':    {'addr': 0x1000, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje entrada modo sleep'},
    'VOL_CELL_UV':        {'addr': 0x1002, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Protección subvoltaje celda'},
    'VOL_CELL_UVPR':      {'addr': 0x1004, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Recuperación subvoltaje celda'},
    'VOL_CELL_OV':        {'addr': 0x1006, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Protección sobrevoltaje celda'},
    'VOL_CELL_OVPR':      {'addr': 0x1008, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Recuperación sobrevoltaje celda'},
    'VOL_BALAN_TRIG':     {'addr': 0x100A, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Diferencia voltaje activa balanceo'},
    'VOL_SOC_100':        {'addr': 0x100C, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje SOC 100%'},
    'VOL_SOC_0':          {'addr': 0x100E, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje SOC 0%'},
    'VOL_CELL_RCV':       {'addr': 0x1010, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje carga recomendado'},
    'VOL_CELL_RFV':       {'addr': 0x1012, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje carga flotante'},
    'VOL_SYS_PWR_OFF':    {'addr': 0x1014, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje apagado automático'},
    'CUR_BAT_COC':        {'addr': 0x1016, 'type': 'UINT32', 'unit': 'mA',    'scale': 1,   'desc': 'Corriente max carga continua'},
    'TIM_BAT_COC_DLY':    {'addr': 0x1018, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Retardo protección sobrecorriente carga'},
    'TIM_BAT_COC_PR_DLY': {'addr': 0x101A, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Recuperación protección sobrecorriente carga'},
    'CUR_BAT_DOC':        {'addr': 0x101C, 'type': 'UINT32', 'unit': 'mA',    'scale': 1,   'desc': 'Corriente max descarga continua'},
    'TIM_BAT_DOC_DLY':    {'addr': 0x101E, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Retardo protección sobrecorriente descarga'},
    'TIM_BAT_DOC_PR_DLY': {'addr': 0x1020, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Recuperación protección sobrecorriente descarga'},
    'TIM_BAT_SCP_PR_DLY': {'addr': 0x1022, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Recuperación protección cortocircuito'},
    'CUR_BALAN_MAX':      {'addr': 0x1024, 'type': 'UINT32', 'unit': 'mA',    'scale': 1,   'desc': 'Corriente máxima de balanceo'},
    'TMP_BAT_COT':        {'addr': 0x1026, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Protección sobretemperatura carga'},
    'TMP_BAT_COTPR':      {'addr': 0x1028, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Recuperación sobretemperatura carga'},
    'TMP_BAT_DOT':        {'addr': 0x102A, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Protección sobretemperatura descarga'},
    'TMP_BAT_DOTPR':      {'addr': 0x102C, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Recuperación sobretemperatura descarga'},
    'TMP_BAT_CUT':        {'addr': 0x102E, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Protección baja temperatura carga'},
    'TMP_BAT_CUTPR':      {'addr': 0x1030, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Recuperación baja temperatura carga'},
    'TMP_MOS_OT':         {'addr': 0x1032, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Protección sobretemperatura MOS'},
    'TMP_MOS_OTPR':       {'addr': 0x1034, 'type': 'INT32',  'unit': '0.1°C', 'scale': 0.1, 'desc': 'Recuperación sobretemperatura MOS'},
    'CELL_COUNT':         {'addr': 0x1036, 'type': 'UINT32', 'unit': '',      'scale': 1,   'desc': 'Número de celdas'},
    'BAT_CHARGE_EN':      {'addr': 0x1038, 'type': 'UINT32', 'unit': 'bool',  'scale': 1,   'desc': 'Switch de carga (1=ON)'},
    'BAT_DISCHARGE_EN':   {'addr': 0x103A, 'type': 'UINT32', 'unit': 'bool',  'scale': 1,   'desc': 'Switch de descarga (1=ON)'},
    'BALAN_EN':           {'addr': 0x103C, 'type': 'UINT32', 'unit': 'bool',  'scale': 1,   'desc': 'Switch de balanceo (1=ON)'},
    'CAP_BAT_CELL':       {'addr': 0x103E, 'type': 'UINT32', 'unit': 'mAh',   'scale': 1,   'desc': 'Capacidad nominal de batería'},
    'SCP_DELAY':          {'addr': 0x1040, 'type': 'UINT32', 'unit': 'µs',    'scale': 1,   'desc': 'Retardo protección cortocircuito'},
    'VOL_START_BALAN':    {'addr': 0x1042, 'type': 'UINT32', 'unit': 'mV',    'scale': 1,   'desc': 'Voltaje inicio de balanceo'},
    # Resistencias cableado: 0x1044 a 0x1083 (32 × UINT32, stride 2)
    'DEV_ADDR':           {'addr': 0x1084, 'type': 'UINT32', 'unit': '',      'scale': 1,   'desc': 'Dirección Modbus ID'},
    'TIM_PRODISCHARGE':   {'addr': 0x1086, 'type': 'UINT32', 'unit': 's',     'scale': 1,   'desc': 'Tiempo de pre-descarga'},
    'CONFIG_FLAGS':       {'addr': 0x108A, 'type': 'UINT16', 'unit': 'bitmask','scale': 1,  'desc': 'Flags de configuración'},
    'TIM_SMART_SLEEP':    {'addr': 0x108C, 'type': 'UINT16', 'unit': 'h',     'scale': 1,   'desc': 'Tiempo smart sleep'},
}

CONFIG_FLAG_BITS = {
    0: 'Calefacción',
    1: 'Deshabilitar sensor temp',
    2: 'GPS Heartbeat',
    3: 'Puerto RS485/CAN',
    4: 'LCD siempre encendido',
    5: 'Cargador dedicado',
    6: 'Smart Sleep',
    7: 'Deshab. limitación paralelo',
    8: 'Almacenamiento periódico',
    9: 'Modo flotante',
}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 0x1200 — Datos en tiempo real (Solo lectura)
# Direcciones CONFIRMADAS para firmware v27 por sondeo empírico.
# El doc V1.1 NO coincide con FW v27; se usan las verificadas.
# ═══════════════════════════════════════════════════════════════════════════════

REALTIME_REGISTERS = {
    # Celdas y estadísticas
    'CELL_VOL_AVE':       {'addr': 0x1222, 'type': 'UINT16', 'unit': 'mV',    'scale': 1,    'desc': 'Voltaje promedio de celdas'},
    'CELL_VDIF_MAX':      {'addr': 0x1223, 'type': 'UINT16', 'unit': 'mV',    'scale': 1,    'desc': 'Diferencia máxima voltaje'},
    'MAX_VOL_CELL_NBR':   {'addr': 0x1224, 'type': 'UINT8_HIGH', 'unit': '',  'scale': 1,    'desc': 'Nº celda voltaje máximo'},
    'MIN_VOL_CELL_NBR':   {'addr': 0x1224, 'type': 'UINT8_LOW',  'unit': '',  'scale': 1,    'desc': 'Nº celda voltaje mínimo'},

    # Temperaturas (confirmadas v27 por sondeo empírico)
    'TEMP_MOS':           {'addr': 0x1285, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura placa MOS'},
    'TEMP_BAT1':          {'addr': 0x128E, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura batería sensor 1'},
    'TEMP_BAT2':          {'addr': 0x128F, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura batería sensor 2'},
    'TEMP_BAT3':          {'addr': 0x12BC, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura batería sensor 3'},
    'TEMP_BAT4':          {'addr': 0x12BD, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura batería sensor 4'},
    'TEMP_BAT5':          {'addr': 0x12BE, 'type': 'INT16',  'unit': '0.1°C', 'scale': 0.1,  'desc': 'Temperatura batería sensor 5'},

    # Pack (confirmados v27)
    'BAT_VOL':            {'addr': 0x1289, 'type': 'UINT16', 'unit': 'V',     'scale': 0.001,'desc': 'Voltaje total de batería'},
    'BAT_CURRENT':        {'addr': 0x128C, 'type': 'INT32',  'unit': 'A',     'scale': 0.001,'desc': 'Corriente de batería (+carga, -descarga)'},

    # Balanceo (confirmados v27)
    'BALAN_CURRENT':      {'addr': 0x1286, 'type': 'INT16',  'unit': 'A',     'scale': 0.001,'desc': 'Corriente de balanceo'},

    # SOC / Capacidad / Ciclos (confirmados v27)
    'SOC':                {'addr': 0x1293, 'type': 'UINT8_LOW', 'unit': '%',  'scale': 1,    'desc': 'Estado de carga SOC'},
    'BALAN_STA':          {'addr': 0x1293, 'type': 'UINT8_HIGH','unit': '',   'scale': 1,    'desc': 'Estado balanceo (2=desc, 1=carga, 0=off)'},
    'SOC_CAP_REMAIN':     {'addr': 0x1294, 'type': 'UINT32', 'unit': 'Ah',    'scale': 0.001,'desc': 'Capacidad restante'},
    'SOC_FULL_CHARGE_CAP':{'addr': 0x1296, 'type': 'UINT32', 'unit': 'Ah',    'scale': 0.001,'desc': 'Capacidad carga completa actual'},
    'SOC_CYCLE_CAP':      {'addr': 0x12B4, 'type': 'UINT32', 'unit': 'Ah',    'scale': 0.001,'desc': 'Capacidad total acumulada en ciclos'},
    'SOC_CYCLE_COUNT':    {'addr': 0x12B6, 'type': 'UINT16', 'unit': '',      'scale': 1,    'desc': 'Número de ciclos'},

    # Estado carga/descarga: 0x12B8 NO es un registro estable.
    # Lectura directa: 0x0101 (ambos ON). Durante carga activa: 0x6400 (HI=100=SOC, LO=0).
    # El registro parece cambiar de contenido según modo de operación. No confirmado.
    # 'CHARGE_STA':       {'addr': 0x12B8, 'type': 'UINT8_LOW',  'unit': 'bool', 'scale': 1, 'desc': 'Estado carga (1=activo)'},
    # 'DISCHARGE_STA':    {'addr': 0x12B8, 'type': 'UINT8_HIGH', 'unit': 'bool', 'scale': 1, 'desc': 'Estado descarga (1=activo)'},


    # Runtime (confirmado v27)
    'RUNTIME':            {'addr': 0x129E, 'type': 'UINT32', 'unit': 's',     'scale': 1,    'desc': 'Tiempo de funcionamiento'},

    # Alarmas (confirmado v27)
    'ALARMS':             {'addr': 0x12A1, 'type': 'UINT32', 'unit': 'bitmask','scale': 1,   'desc': 'Registro de alarmas (22 bits)'},

    # SOH: 0x12B9 lee 0 consistentemente — dirección no confirmada, deshabilitado
    # 'SOC_SOH':          {'addr': 0x12B9, 'type': 'UINT8_HIGH', 'unit': '%', 'scale': 1,    'desc': 'SOH estimado'},

    # Tiempos de recuperación restantes
    'TIME_DC_OCPR':       {'addr': 0x12C4, 'type': 'UINT16', 'unit': 's',     'scale': 1,    'desc': 'Tiempo recuperación sobrecorriente desc.'},
    'TIME_DC_SCPR':       {'addr': 0x12C5, 'type': 'UINT16', 'unit': 's',     'scale': 1,    'desc': 'Tiempo recuperación cortocircuito desc.'},
    'TIME_COCPR':         {'addr': 0x12C6, 'type': 'UINT16', 'unit': 's',     'scale': 1,    'desc': 'Tiempo recuperación sobrecorriente carga'},
    'TIME_UVPR':          {'addr': 0x12C8, 'type': 'UINT16', 'unit': 's',     'scale': 1,    'desc': 'Tiempo recuperación subvoltaje celda'},
    'TIME_OVPR':          {'addr': 0x12C9, 'type': 'UINT16', 'unit': 's',     'scale': 1,    'desc': 'Tiempo recuperación sobrevoltaje celda'},

    # Diagnóstico / Sensores extra
    'SYS_RUN_TICKS':      {'addr': 0x12F0, 'type': 'UINT32', 'unit': '0.1s', 'scale': 0.1,  'desc': 'Latidos del sistema'},
    'RTC_TICKS':          {'addr': 0x12F4, 'type': 'UINT32', 'unit': 'ticks','scale': 1,     'desc': 'Contador RTC (desde 2020-01-01)'},
}

ALARM_BITS = {
    0:  'Resistencia cable alta',
    1:  'MOS sobre-temperatura',
    2:  'Nº celdas incorrecto',
    3:  'Error sensor corriente',
    4:  'Sobrevoltaje celda',
    5:  'Sobrevoltaje pack',
    6:  'Sobrecorriente carga',
    7:  'Cortocircuito carga',
    8:  'Sobre-temperatura carga',
    9:  'Baja-temperatura carga',
    10: 'Error comunicación interna',
    11: 'Subvoltaje celda',
    12: 'Subvoltaje pack',
    13: 'Sobrecorriente descarga',
    14: 'Cortocircuito descarga',
    15: 'Sobre-temperatura descarga',
    16: 'Error MOS carga',
    17: 'Error MOS descarga',
    18: 'GPS desconectado',
    19: 'Cambiar contraseña',
    20: 'Fallo inicio descarga',
    21: 'Alarma sobre-temp batería',
}

BALANCE_STATUS_MAP = {0: 'Off', 1: 'Charging', 2: 'Discharging'}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 0x1400 — Información del dispositivo
# Cada ASCII de N bytes ocupa N/2 registros Modbus. Stride = longitud/2.
# ═══════════════════════════════════════════════════════════════════════════════

DEVICE_INFO_REGISTERS = {
    'MANUFACTURER_ID':    {'addr': 0x1400, 'type': 'ASCII', 'length': 16, 'desc': 'Modelo del fabricante'},
    'HW_VERSION':         {'addr': 0x1408, 'type': 'ASCII', 'length': 8,  'desc': 'Versión de hardware'},
    'SW_VERSION':         {'addr': 0x140C, 'type': 'ASCII', 'length': 8,  'desc': 'Versión de software/firmware'},
    'ODD_RUN_TIME':       {'addr': 0x1410, 'type': 'UINT32', 'unit': 's', 'scale': 1, 'desc': 'Tiempo total funcionamiento acumulado'},
    'PWR_ON_TIMES':       {'addr': 0x1412, 'type': 'UINT32', 'unit': '',  'scale': 1, 'desc': 'Número de encendidos'},
    'BLE_NAME':           {'addr': 0x1414, 'type': 'ASCII', 'length': 16, 'desc': 'Nombre Bluetooth (no oficial)'},
    'BLE_PIN':            {'addr': 0x141C, 'type': 'ASCII', 'length': 16, 'desc': 'PIN Bluetooth (no oficial)'},
    'FIRST_ON_DATE':      {'addr': 0x1424, 'type': 'ASCII', 'length': 8,  'desc': 'Fecha primer encendido (no oficial)'},
    'SERIAL_NO':          {'addr': 0x1428, 'type': 'ASCII', 'length': 16, 'desc': 'Número de serie (no oficial)'},
    'USER_PRIVATE_DATA':  {'addr': 0x1430, 'type': 'ASCII', 'length': 16, 'desc': 'Datos privados usuario (no oficial)'},
    'PASSWORD':           {'addr': 0x1438, 'type': 'ASCII', 'length': 16, 'desc': 'Contraseña (no oficial)'},
    'USER_DATA2':         {'addr': 0x1440, 'type': 'ASCII', 'length': 16, 'desc': 'Datos de usuario 2 (no oficial)'},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Clase principal: JKBMSV2Client
# ═══════════════════════════════════════════════════════════════════════════════

class JKBMSV2Client(BaseModbusClient):
    """
    Cliente para leer TODOS los registros del JK BMS.
    Combina direcciones del doc V1.1 y sondeo empírico FW v27.
    Solo parseo, sin funcionalidad MQTT.
    """

    NUM_CELLS = 16

    def _read_block(self, start_addr, word_count):
        """Lee un bloque de registros y devuelve dict {addr: value}."""
        mem = {}
        for offset in range(0, word_count, 64):
            chunk_count = min(64, word_count - offset)
            regs = self.read_holding_registers(start_addr + offset, chunk_count)
            if regs:
                for i, v in enumerate(regs):
                    mem[start_addr + offset + i] = v
        return mem

    def _decode_from_mem(self, mem, reg_def):
        """Decodifica un registro individual desde la memoria leída."""
        addr = reg_def['addr']
        n = words_needed(reg_def)
        raw = []
        for i in range(n):
            v = mem.get(addr + i)
            if v is None:
                return None
            raw.append(v)
        val = decode_register(raw, reg_def)
        if val is not None and 'scale' in reg_def and reg_def['scale'] != 1:
            val = round(val * reg_def['scale'], 4)
        return val

    def read_config_block(self):
        """Lee y decodifica el bloque 0x1000 (configuración)."""
        mem = self._read_block(0x1000, 0x8E)  # 0x1000 a 0x108D

        data = {}
        for key, reg in CONFIG_REGISTERS.items():
            val = self._decode_from_mem(mem, reg)
            if val is not None:
                data[key] = val

        # Resistencias de cableado (0x1044 a 0x1083, 32 × UINT32, stride 2)
        wire_res = []
        for i in range(32):
            addr = 0x1044 + i * 2
            hi = mem.get(addr)
            lo = mem.get(addr + 1)
            if hi is not None and lo is not None:
                wire_res.append((hi << 16) | lo)
            else:
                break
        if wire_res:
            data['CELL_CON_WIRE_RES'] = wire_res

        if 'CONFIG_FLAGS' in data:
            data['CONFIG_FLAGS_DECODED'] = decode_config_flags(data['CONFIG_FLAGS'])

        return data

    def read_realtime_block(self):
        """Lee y decodifica el bloque 0x1200 (datos en tiempo real)."""
        # Leer en sub-bloques para cubrir todo el rango necesario
        mem = {}
        ranges = [
            (0x1200, 64),   # Celdas + stats (0x1200-0x123F)
            (0x1240, 64),   # Resistencias + extras (0x1240-0x127F)
            (0x1280, 64),   # MOS temp, bat current, etc (0x1280-0x12BF)
            (0x12C0, 64),   # Recovery timers, etc (0x12C0-0x12FF)
        ]
        for start, count in ranges:
            block = self._read_block(start, count)
            mem.update(block)

        data = {}

        # Voltajes de celdas (0x1200, stride 1, UINT16) -> Convertir a V
        cell_voltages = []
        for i in range(self.NUM_CELLS):
            v = mem.get(0x1200 + i)
            if v is not None:
                cell_voltages.append(round(v / 1000.0, 3))
        if cell_voltages:
            data['CELL_VOLTAGES'] = cell_voltages

        # Resistencias de celdas (confirmado v27: 0x124D, stride 1, UINT16)
        cell_res = []
        for i in range(self.NUM_CELLS):
            v = mem.get(0x124D + i)
            if v is not None:
                cell_res.append(v)
        if cell_res:
            data['CELL_RESISTANCES'] = cell_res

        # Registros individuales
        for key, reg in REALTIME_REGISTERS.items():
            val = self._decode_from_mem(mem, reg)
            if val is not None:
                data[key] = val

        # Post-procesado
        if 'ALARMS' in data:
            data['ALARMS_DECODED'] = decode_alarms(int(data['ALARMS']))

        if 'BALAN_STA' in data:
            data['BALAN_STA_TEXT'] = BALANCE_STATUS_MAP.get(int(data['BALAN_STA']), str(data['BALAN_STA']))

        if 'RUNTIME' in data:
            data['RUNTIME_TEXT'] = format_uptime(data['RUNTIME'])

        # Potencia derivada
        bat_v = data.get('BAT_VOL', 0)    # en V (ya escalado)
        bat_i = data.get('BAT_CURRENT', 0) # en A (ya escalado)
        if isinstance(bat_v, (int, float)) and isinstance(bat_i, (int, float)):
            data['BAT_POWER_W'] = round(bat_v * bat_i, 2)
            if bat_i > 0:
                data['CHARGING_POWER'] = round(bat_v * bat_i, 2)
                data['DISCHARGING_POWER'] = 0.0
            else:
                data['CHARGING_POWER'] = 0.0
                data['DISCHARGING_POWER'] = round(abs(bat_v * bat_i), 2)

        return data

    def read_device_info_block(self):
        """Lee y decodifica el bloque 0x1400 (información del dispositivo)."""
        mem = self._read_block(0x1400, 0x48)  # 0x1400 a 0x1447

        data = {}
        for key, reg in DEVICE_INFO_REGISTERS.items():
            val = self._decode_from_mem(mem, reg)
            if val is not None:
                data[key] = val

        if 'ODD_RUN_TIME' in data:
            data['ODD_RUN_TIME_TEXT'] = format_uptime(data['ODD_RUN_TIME'])

        return data

    def get_all_data(self):
        """
        Lee TODOS los bloques y devuelve un diccionario plano.
        Incluye '_raw_data' con los registros crudos para depuración.
        """
        all_data = {'_raw_data': {}}
        
        # 1. Device Info (0x1400)
        info = self.read_device_info_block()
        if info:
            all_data.update(info)
            # Inyectar claves para que coincidan con lo que main.py espera
            if 'SW_VERSION' in info:
                all_data['FIRMWARE_VERSION'] = info['SW_VERSION']
            if 'HW_VERSION' in info:
                all_data['HARDWARE_VERSION'] = info['HW_VERSION']
        
        # 2. Realtime (0x1200)
        realtime = self.read_realtime_block()
        if realtime:
            all_data.update(realtime)
            
        # 3. Config (0x1000) - Solo algunos campos clave para no saturar
        config = self.read_config_block()
        if config:
            # Solo pasamos los switches y valores de balanceo
            for k in ['BAT_CHARGE_EN', 'BAT_DISCHARGE_EN', 'BALAN_EN', 'BALAN_START_VOL', 'CAP_BAT_CELL', 'VOL_START_BALAN']:
                if k in config:
                    all_data[k] = config[k]
            if 'CONFIG_FLAGS_DECODED' in config:
                all_data['CONFIG_FLAGS_DECODED'] = config['CONFIG_FLAGS_DECODED']

        return all_data

    def get_discovery_sensors(self) -> list:
        """Genera la lista de sensores para HA MQTT Discovery v2."""
        sensors = []
        class_map = {
            'V': 'voltage', 'A': 'current', 'W': 'power',
            '0.1°C': 'temperature', '°C': 'temperature', 
            '%': 'battery', 'Ah': None, 'mAh': None, 'mV': 'voltage',
            'mA': 'current', 's': 'duration', 'h': 'duration'
        }

        # 1. Sensores de Tiempo Real
        for key, reg in REALTIME_REGISTERS.items():
            unit = reg.get('unit', '')
            dclass = class_map.get(unit)
            
            # Casos especiales
            if key == 'ALARMS': continue # Se procesa como string en ALARMS_DECODED
            
            sensor = {
                'id': key.lower(),
                'name': key.replace('_', ' ').title(),
                'unit': unit if unit != '0.1°C' else '°C',
                'device_class': dclass,
                'value_template': f"{{{{ value_json.{key} }}}}"
            }
            
            # Marcar estados como diagnósticos o mediciones
            if unit in ('V', 'A', 'W', '%', 'Ah'):
                sensor['state_class'] = 'measurement'
                
            sensors.append(sensor)

        # 2. Sensores Extra (Derivados / Procesados)
        extra_sensors = [
            {'id': 'alarms_decoded', 'name': 'Active Alarms', 'value_template': '{{ value_json.ALARMS_DECODED | join(", ") }}'},
            {'id': 'balan_sta_text', 'name': 'Balance Status', 'value_template': '{{ value_json.BALAN_STA_TEXT }}'},
            {'id': 'runtime_text',   'name': 'Runtime', 'value_template': '{{ value_json.RUNTIME_TEXT }}'},
            {'id': 'bat_power_w',    'name': 'Battery Power', 'unit': 'W', 'device_class': 'power', 'state_class': 'measurement', 'value_template': '{{ value_json.BAT_POWER_W }}'},
            {'id': 'charging_power', 'name': 'Charging Power', 'unit': 'W', 'device_class': 'power', 'state_class': 'measurement', 'value_template': '{{ value_json.CHARGING_POWER }}'},
            {'id': 'discharging_power', 'name': 'Discharging Power', 'unit': 'W', 'device_class': 'power', 'state_class': 'measurement', 'value_template': '{{ value_json.DISCHARGING_POWER }}'}
        ]
        sensors.extend(extra_sensors)

        # 3. Sensores Binarios (Config Switches)
        binary_switches = [
            {'key': 'BAT_CHARGE_EN',    'name': 'Charge Switch'},
            {'key': 'BAT_DISCHARGE_EN', 'name': 'Discharge Switch'},
            {'key': 'BALAN_EN',         'name': 'Balance Switch'}
        ]
        for b in binary_switches:
            sensors.append({
                'id': b['key'].lower(),
                'name': b['name'],
                'component': 'binary_sensor',
                'device_class': 'connectivity', # o None
                'payload_on': 1,
                'payload_off': 0,
                'value_template': f"{{{{ value_json.{b['key']} }}}}"
            })

        # 4. Info del Dispositivo (Serial, Versiones)
        for key in ['MANUFACTURER_ID', 'HW_VERSION', 'SW_VERSION', 'SERIAL_NO', 'ODD_RUN_TIME_TEXT']:
            reg = DEVICE_INFO_REGISTERS.get(key, {})
            sensors.append({
                'id': key.lower(),
                'name': key.replace('_', ' ').title(),
                'value_template': f"{{{{ value_json.{key} }}}}"
            })

        # 5. Voltajes de celdas (16 celdas)
        for i in range(self.NUM_CELLS):
            sensors.append({
                'id': f'cell_voltage_{i+1}',
                'name': f'Cell Voltage {i+1}',
                'unit': 'V',
                'device_class': 'voltage',
                'state_class': 'measurement',
                'value_template': f"{{{{ value_json.CELL_VOLTAGES[{i}] }}}}"
            })

        # 6. Resistencias de celdas (16 celdas)
        for i in range(self.NUM_CELLS):
            sensors.append({
                'id': f'cell_resistance_{i+1}',
                'name': f'Cell Resistance {i+1}',
                'unit': 'mΩ',
                'state_class': 'measurement',
                'value_template': f"{{{{ value_json.CELL_RESISTANCES[{i}] | float / 1000.0 }}}}"
            })

        return sensors
