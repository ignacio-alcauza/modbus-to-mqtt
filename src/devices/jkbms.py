import struct
import logging
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.jkbms")

# ─────────────────────────────────────────────────────────────────────────────
# JK BMS JK-PB2A16S20P  —  Firmware v27 (hw v19)
# Holding Registers, función 0x03
#
# El firmware v27 difiere del doc oficial V1.1 en el bloque 0x1280–0x12CF:
# el sub-bloque de SOC/capacidad/corriente aparece 8 registros más arriba
# de lo que indica la documentación. Se usan las direcciones confirmadas
# por sonda exhaustiva de memoria.
# ─────────────────────────────────────────────────────────────────────────────

REGISTERS = {

    # ── Voltajes Celdas ×16 (step=1 contiguous, confirmed v27 probe) ─────────
    'CELL_VOLTAGES': {
        'addr': 0x1200,
        'count': 16,
        'step': 1,      # Contiguous in v27
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },

    # ── Resistencias Cables ×16 (empírico v27: 0x124D definitive) ────────────
    'CELL_RESISTANCES': {
        'addr': 0x124D,
        'count': 16,
        'step': 1,
        'type': 'UINT16',
        'unit': 'mΩ',
        'scale': 0.001,
    },

    # ── Estadísticas de Celdas (v27 reality: 0x1220 range) ───────────────────
    'CELL_AVG_VOLTAGE': {
        'addr': 0x1222,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_VOLT_DIFF': {
        'addr': 0x1225,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_MAX_NO': {
        'addr': 0x123B,     # Empírico v27: byte bajo
        'type': 'UINT8_LOW',
    },
    'CELL_MIN_NO': {
        'addr': 0x123C,     # Empírico v27: byte alto
        'type': 'UINT8_HIGH',
    },

    # ── Temperaturas ──────────────────────────────────────────────────────────
    # Empírico v27: MOS @ 0x1285 = 16.7°C. Doc dice 0x128A pero da 2.2°C (incorrecto).
    'TEMP_MOS': {
        'addr': 0x1285,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    # T1 @ 0x1296, T2 @ 0x1297 (empírico v27)
    'TEMP_T1': {
        'addr': 0x1296,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T2': {
        'addr': 0x1297,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    # T4 @ 0x12F5, T5 @ 0x12F6 (empírico v27, confirmados ~14-15°C)
    'TEMP_T4': {
        'addr': 0x12F5,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T5': {
        'addr': 0x12F6,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },

    # ── Voltaje Pack (v27: 0x1291) ──────────────────────────────────────────
    'BAT_VOLTAGE': {
        'addr': 0x1291,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },

    # ── Corriente (v27: 0x1295) ─────────────────────────────────────────────
    # INT16, mA → A. Positivo = carga, Negativo = descarga.
    'BAT_CURRENT': {
        'addr': 0x1295,
        'type': 'INT16',
        'unit': 'A',
        'scale': 0.001,
    },
    'BALANCING_CURRENT': {
        'addr': 0x1286,     # De sonda: 0x1286=3 (0.003A)
        'type': 'INT16',
        'unit': 'A',
        'scale': 0.001,
    },

    # ── SOC % (v27: 0x12A3) ────────────────────────────────────────────────
    'SOC_PERCENT': {
        'addr': 0x12A3,
        'type': 'UINT16',
        'unit': '%',
    },
    'BALANCE_STATUS': {
        'addr': 0x12A8,     # De sonda: 0x12A4 row shows 77 at A3, then 3, 45667, 4, 51856, 0, 0, 2...
        'type': 'UINT16',
    },

    # ── Capacidades (v27 definitive) ─────────────────────────────────────────
    # SOCCapRemain: UINT32 @ 0x12A4-12A5 (3<<16 | 45667 = 242275 mAh)
    'SOC_CAP_REMAIN': {
        'addr': 0x12A4,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    # SOCFullChargeCap: UINT32 @ 0x12A6-12A7 (4<<16 | 51856 = 314000 mAh)
    'SOC_FULL_CAP': {
        'addr': 0x12A6,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    # Total Charge Capacity: UINT32 @ 0x12AA-12AB (2<<16 | 12688 = 143760 mAh)
    'TOTAL_CHG_CAPACITY': {
        'addr': 0x12AA,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    'CYCLE_COUNT': {
        'addr': 0x1292,     # De sonda: 0x1292=24 (probable ciclo count)
        'type': 'UINT16',
    },

    # ── Uptime (v27: 0x12AE-12AF) ────────────────────────────────────────────
    'UPTIME': {
        'addr': 0x12AE,
        'type': 'UINT32',
        'count': 2,
    },

    # ── Estado Carga/Descarga (v27: 0x12B8) ──────────────────────────────────
    'CHARGE': {
        'addr': 0x12B8,
        'type': 'UINT8_HIGH',
    },
    'DISCHARGE': {
        'addr': 0x12B8,
        'type': 'UINT8_LOW',
    },

    # ── Alarmas (v27: 0x12BF) ────────────────────────────────────────────────
    'ALARMS_32BIT': {
        'addr': 0x12BF,
        'type': 'UINT16',
        'subtype': 'BITMASK',
    },

    # ── Configuración (zona RW 0x1070–0x1086) ───────────────────────────
    # Dump raw: 0x1070=[0,1] 0x1072=[0,1] 0x1074=[0,1] 0x107A=[0,3300]
    # Los switches son UINT16 en la palabra baja (offset+1)
    'CHARGE_SWITCH': {
        'addr': 0x1071,
        'type': 'UINT16',
    },
    'DISCHARGE_SWITCH': {
        'addr': 0x1073,
        'type': 'UINT16',
    },
    'BALANCE_SWITCH': {
        'addr': 0x1079,
        'type': 'UINT16',
    },
    # VolStartBalan @ 0x107B  UINT16, mV → V
    'VOL_START_BALAN': {
        'addr': 0x107B,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
}

ALARM_BITS = {
    0: "Resistance anomaly",
    1: "Cell undervoltage",
    2: "Cell overvoltage",
    3: "Charge over-current",
    4: "Discharge over-current",
    5: "Discharge short-circuit",
    6: "Cell over-temperature",
    7: "MOS over-temperature",
    8: "Cell low-temperature",
    9: "Internal communication anomaly",
    10: "Cell differential anomaly",
    11: "Discharge MOS anomaly",
    12: "Charge MOS anomaly",
    13: "Balance MOS anomaly",
    14: "BMS over-temperature",
    15: "Internal battery anomaly",
}


class JKBMSClient(BaseModbusClient):

    def _fetch_all(self) -> dict:
        """Lee bloques de registros en trozos de 16 para máxima compatibilidad."""
        data = {}
        ranges = [
            (0x1200, 96), # Cubre 0x1200 a 0x125F (Celdas, Stats, Resistencias)
            (0x1280, 16), # MOS Temp, Bal. Current
            (0x1290, 64), # Sensores Pack + SOC + Capacidad + Uptime
            (0x12F0, 16), # Temps extra
            (0x1070, 32), # Config
        ]
        for start, count in ranges:
            for base in range(start, start + count, 16):
                chunk = self.read_holding_registers(base, 16)
                if chunk:
                    for i, v in enumerate(chunk):
                        data[base + i] = v
        return data

    def decode_value(self, chunk: list, reg_def: dict):
        rtype = reg_def.get('type', 'UINT16')
        scale = reg_def.get('scale', 1.0)

        if rtype in ('UINT32', 'INT32', 'FLOAT32') and len(chunk) < 2:
            return None
        if rtype == 'UINT16':
            val = chunk[0]
        elif rtype == 'INT16':
            val = struct.unpack('>h', struct.pack('>H', chunk[0]))[0]
        elif rtype == 'UINT32':
            val = (chunk[0] << 16) | chunk[1]
        elif rtype == 'INT32':
            val = struct.unpack('>i', struct.pack('>I', (chunk[0] << 16) | chunk[1]))[0]
        elif rtype == 'FLOAT32':
            return round(struct.unpack('>f', struct.pack('>HH', chunk[0], chunk[1]))[0], 3)
        elif rtype == 'UINT8_LOW':
            val = chunk[0] & 0xFF
        elif rtype == 'UINT8_HIGH':
            val = (chunk[0] >> 8) & 0xFF
        else:
            val = chunk[0]

        return round(val * scale, 3)

    def _format_uptime(self, seconds: int) -> str:
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "0s"
        minutes, sec = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        if days > 0:
            h_str = f", {hours}h" if hours else ""
            return f"{days}d{h_str}"
        parts = []
        if hours:    parts.append(f"{hours}h")
        if minutes:  parts.append(f"{minutes}m")
        if sec or not parts: parts.append(f"{sec}s")
        return " ".join(parts)

    def get_all_data(self) -> dict:
        mem = self._fetch_all()
        data = {}

        for key, reg in REGISTERS.items():
            addr   = reg['addr']
            rtype  = reg.get('type', 'UINT16')
            step   = reg.get('step', 1)

            # Arrays con paso variable (celdas)
            if key in ('CELL_VOLTAGES', 'CELL_RESISTANCES'):
                vals = []
                for i in range(reg['count']):
                    v = mem.get(addr + i * step)
                    if v is None:
                        break
                    vals.append(round(v * reg.get('scale', 1.0), 4))
                if vals:
                    data[key] = vals
                continue

            # Registros de 2 palabras (UINT32/INT32)
            if rtype in ('UINT32', 'INT32', 'FLOAT32'):
                chunk = [mem.get(addr), mem.get(addr + 1)]
                if None in chunk:
                    continue
            else:
                v = mem.get(addr)
                if v is None:
                    continue
                chunk = [v]

            val = self.decode_value(chunk, reg)
            if val is None:
                continue

            # Post-procesado
            if key == 'UPTIME':
                val = self._format_uptime(val)
            elif key in ('CHARGE', 'DISCHARGE', 'CHARGE_SWITCH', 'DISCHARGE_SWITCH', 'BALANCE_SWITCH'):
                val = 'ON' if val else 'OFF'
            elif key == 'BALANCE_STATUS':
                val = {0: 'Off', 1: 'Charging', 2: 'Discharging'}.get(int(val), str(val))

            data[key] = val

        # Potencia derivada
        bat_v = data.get('BAT_VOLTAGE', 0.0)
        bat_i = data.get('BAT_CURRENT', 0.0)
        bat_p = bat_v * bat_i
        if bat_i > 0:
            data['CHARGING_POWER']    = round(bat_p, 0)
            data['DISCHARGING_POWER'] = 0.0
        else:
            data['CHARGING_POWER']    = 0.0
            data['DISCHARGING_POWER'] = round(abs(bat_p), 0)

        # Alarmas decodificadas
        alarm_val = int(data.get('ALARMS_32BIT', 0))
        alarms = [ALARM_BITS[b] for b in ALARM_BITS if (alarm_val >> b) & 1]
        data['PARSED_ALARMS'] = alarms if alarms else ['Normal']

        return data

    def get_discovery_sensors(self) -> list:
        sensors = []
        class_map = {
            'V': 'voltage', 'A': 'current', 'W': 'power',
            '°C': 'temperature', '%': 'battery', 'Ah': None, 'mΩ': None,
        }
        for key, reg in REGISTERS.items():
            if key in ('CELL_VOLTAGES', 'CELL_RESISTANCES'):
                unit = reg.get('unit')
                prefix = 'Cell Voltage' if key == 'CELL_VOLTAGES' else 'Cell Resistance'
                for i in range(reg['count']):
                    sensors.append({
                        'id':             f"jkbms_{key.lower()}_{i + 1}",
                        'name':           f"{prefix} {i + 1}",
                        'unit':           unit,
                        'device_class':   class_map.get(unit),
                        'value_template': f"{{{{ value_json.{key}[{i}] }}}}",
                    })
            elif key == 'ALARMS_32BIT':
                continue
            else:
                unit = reg.get('unit')
                sensors.append({
                    'id':             f"jkbms_{key.lower()}",
                    'name':           key.replace('_', ' ').title(),
                    'unit':           unit,
                    'device_class':   class_map.get(unit),
                    'value_template': f"{{{{ value_json.{key} }}}}",
                })

        sensors += [
            {
                'id': 'jkbms_parsed_alarms', 'name': 'Active Alarms',
                'value_template': '{{ value_json.PARSED_ALARMS | join(", ") }}'
            },
            {
                'id': 'jkbms_charging_power', 'name': 'Charging Power',
                'unit': 'W', 'device_class': 'power',
                'value_template': '{{ value_json.CHARGING_POWER }}'
            },
            {
                'id': 'jkbms_discharging_power', 'name': 'Discharging Power',
                'unit': 'W', 'device_class': 'power',
                'value_template': '{{ value_json.DISCHARGING_POWER }}'
            },
        ]
        return sensors
