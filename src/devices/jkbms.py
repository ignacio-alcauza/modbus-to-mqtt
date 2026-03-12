import struct
import logging
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.jkbms")

# ─────────────────────────────────────────────────────────────────────────────
# JK-PB2A16S20P  Modbus TCP Register Map
# Verified live via exhaustive probe against firmware v27 / hw v19.
# All addresses are Modbus holding-register WORD addresses.
#
# We read 4 x 64-register blocks:
#   0x1200–0x123F  cell voltages, cell stats
#   0x1240–0x127F  cell status bitmask, avg/diff/max-min cells
#   0x1280–0x12BF  temperatures, pack V/I, SOC, capacity, cycles
#   0x12C0–0x12FF  charge/discharge byte flags, extra data
#
# NOTE: The official JK BMS Modbus doc (V1.1) uses byte-offset addressing
# that does NOT map 1:1 to Modbus register addresses via the Elfin EW11A.
# All addresses below are ACTUAL register addresses confirmed live.
# ─────────────────────────────────────────────────────────────────────────────

REGISTERS = {
    # ── Cell Voltages (×16) ───────────────────────────────────────────────────
    'CELL_VOLTAGES': {
        'addr': 0x1200,
        'count': 16,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },

    # ── Cell Statistics ───────────────────────────────────────────────────────
    'CELL_AVG_VOLTAGE': {
        'addr': 0x1222,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_VOLT_DIFF': {
        'addr': 0x1223,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_MAX_NO': {
        'addr': 0x1224,
        'type': 'UINT8_HIGH',
    },
    'CELL_MIN_NO': {
        'addr': 0x1224,
        'type': 'UINT8_LOW',
    },

    # ── Cell Resistances (×16) ────────────────────────────────────────────────
    'CELL_RESISTANCES': {
        'addr': 0x1225,
        'count': 16,
        'type': 'UINT16',
        'unit': 'mΩ',
        'scale': 0.001,
    },

    # ── Temperatures ──────────────────────────────────────────────────────────
    'TEMP_MOS': {
        'addr': 0x1285,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T1': {
        'addr': 0x128E,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T2': {
        'addr': 0x128F,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T3': {
        'addr': 0x12BC,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T4': {
        'addr': 0x12BD,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    'TEMP_T5': {
        'addr': 0x12BE,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },

    # ── Pack Voltage & Current ────────────────────────────────────────────────
    'BAT_VOLTAGE': {
        'addr': 0x1289,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'BAT_CURRENT': {
        'addr': 0x128C,
        'type': 'INT32',
        'count': 2,
        'unit': 'A',
        'scale': 0.001,
    },

    # ── SOC & Balance ─────────────────────────────────────────────────────────
    'SOC_PERCENT': {
        'addr': 0x1293,
        'type': 'UINT8_LOW',
        'unit': '%',
    },
    'BALANCE_STATUS': {
        'addr': 0x1293,
        'type': 'UINT8_HIGH',
    },

    # ── Capacity ──────────────────────────────────────────────────────────────
    'SOC_CAP_REMAIN': {
        'addr': 0x1294,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    'SOC_FULL_CAP': {
        'addr': 0x1296,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },

    # ── Uptime ────────────────────────────────────────────────────────────────
    'UPTIME': {
        'addr': 0x129E,
        'type': 'UINT32',
        'count': 2,
    },

    # ── Charge / Discharge MOS State ──────────────────────────────────────────
    'CHARGE': {
        'addr': 0x129C,
        'type': 'UINT32_SWAP',
        'count': 2,
        'subtype': 'BIT_14',
    },
    'DISCHARGE': {
        'addr': 0x129C,
        'type': 'UINT32_SWAP',
        'count': 2,
        'subtype': 'BIT_13',
    },

    # ── Alarms ────────────────────────────────────────────────────────────────
    'ALARMS_32BIT': {
        'addr': 0x12A1,
        'type': 'UINT32_SWAP',
        'count': 2,
        'subtype': 'BITMASK',
    },

    # ── Balancing ─────────────────────────────────────────────────────────────
    'BALANCING_CURRENT': {
        'addr': 0x12A4,
        'type': 'INT16',
        'unit': 'A',
        'scale': 0.001,
    },
    'BALANCE_TRIGGER_VOLTAGE': {
        'addr': 0x12AE,
        'type': 'FLOAT32',
        'count': 2,
        'unit': 'V',
    },

    # ── Cycle Statistics ──────────────────────────────────────────────────────
    'CYCLE_COUNT': {
        'addr': 0x1298,
        'type': 'UINT32',
        'count': 2,
    },
    'TOTAL_CHG_CAPACITY': {
        'addr': 0x129A,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
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

    def decode_value(self, registers, reg_def):
        if not registers:
            return None
        rtype = reg_def.get('type', 'UINT16')
        scale = reg_def.get('scale', 1.0)

        if rtype in ['UINT32', 'INT32', 'UINT32_SWAP', 'INT32_SWAP', 'FLOAT32', 'FLOAT32_SWAP'] and len(registers) < 2:
            return None

        if rtype == 'UINT16':
            val = registers[0]
        elif rtype == 'INT16':
            val = struct.unpack('>h', struct.pack('>H', registers[0]))[0]
        elif rtype == 'UINT32':
            val = (registers[0] << 16) + registers[1]
        elif rtype == 'INT32':
            val = struct.unpack('>i', struct.pack('>I', (registers[0] << 16) + registers[1]))[0]
        elif rtype == 'UINT32_SWAP':
            val = (registers[1] << 16) + registers[0]
        elif rtype == 'INT32_SWAP':
            val = struct.unpack('>i', struct.pack('>I', (registers[1] << 16) + registers[0]))[0]
        elif rtype == 'FLOAT32':
            return round(struct.unpack('>f', struct.pack('>HH', registers[0], registers[1]))[0], 3)
        elif rtype == 'FLOAT32_SWAP':
            return round(struct.unpack('>f', struct.pack('>HH', registers[1], registers[0]))[0], 3)
        elif rtype == 'UINT8_LOW':
            val = registers[0] & 0xFF
        elif rtype == 'UINT8_HIGH':
            val = (registers[0] >> 8) & 0xFF
        else:
            val = registers[0]

        return round(val * scale, 3)

    def _format_uptime(self, seconds: int) -> str:
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "0s"

        minutes, sec = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        years, days = divmod(days, 365)
        months, days = divmod(days, 30)

        if years > 0:
            m_str = f", {months} mes{'es' if months != 1 else ''}" if months > 0 else ""
            return f"{years} año{'s' if years > 1 else ''}{m_str}"
        if months > 0:
            d_str = f", {days} día{'s' if days != 1 else ''}" if days > 0 else ""
            return f"{months} mes{'es' if months != 1 else ''}{d_str}"
        if days > 0:
            h_str = f", {hours}h" if hours > 0 else ""
            return f"{days} día{'s' if days != 1 else ''}{h_str}"

        parts = []
        if hours > 0: parts.append(f"{hours}h")
        if minutes > 0: parts.append(f"{minutes}m")
        if sec > 0 or not parts: parts.append(f"{sec}s")
        return " ".join(parts)

    def get_all_data(self) -> dict:
        data = {}

        # Leer en fragmentos de 32 registros para evitar truncamientos del Elfin/JK.
        # Capturamos desde 0x1200 hasta 0x12BF (192 registros en total).
        full_block = []
        for start in range(0x1200, 0x12C0, 32):
            chunk = self.read_holding_registers(start, 32)
            full_block.extend(chunk or [0] * 32)

        for key, reg in REGISTERS.items():
            addr = reg['addr']
            count = reg.get('count', 1)
            offset = addr - 0x1200

            if 0 <= offset and offset + count <= len(full_block):
                chunk = full_block[offset: offset + count]
                if key in ['CELL_VOLTAGES', 'CELL_RESISTANCES']:
                    data[key] = [round(v * reg.get('scale', 1.0), 3) for v in chunk]
                else:
                    val = self.decode_value(chunk, reg)
                    if val is not None:
                        if key == 'UPTIME':
                            val = self._format_uptime(val)
                        elif reg.get('subtype') == 'BIT_14':
                            val = "ON" if (int(val) & (1 << 14)) else "OFF"
                        elif reg.get('subtype') == 'BIT_13':
                            val = "ON" if (int(val) & (1 << 13)) else "OFF"
                        elif key == 'BALANCE_STATUS':
                            if val == 1: val = "Charging"
                            elif val == 2: val = "Discharging"
                            else: val = "Off"
                    data[key] = val

        # Derived: charging / discharging power (W)
        bat_vol = data.get('BAT_VOLTAGE', 0.0)
        bat_current = data.get('BAT_CURRENT', 0.0)
        bat_power = bat_vol * bat_current

        if bat_current > 0:
            data['CHARGING_POWER'] = round(bat_power, 0)
            data['DISCHARGING_POWER'] = 0.0
        else:
            data['CHARGING_POWER'] = 0.0
            data['DISCHARGING_POWER'] = round(abs(bat_power), 0)

        # Alarm parsing
        alarm_val = int(data.get('ALARMS_32BIT', 0))
        alarms = [ALARM_BITS[b] for b in ALARM_BITS if (alarm_val >> b) & 1]
        data['parsed_alarms'] = alarms if alarms else ["Normal"]

        return data

    def get_discovery_sensors(self) -> list:
        sensors = []

        class_map = {
            'V': 'voltage',
            'mV': 'voltage',
            'A': 'current',
            'W': 'power',
            '°C': 'temperature',
            '%': 'battery',
            'Ah': None,
            's': 'duration',
        }

        for key, reg in REGISTERS.items():
            if key in ['CELL_VOLTAGES', 'CELL_RESISTANCES']:
                count = reg.get('count', 1)
                unit = reg.get('unit')
                dclass = class_map.get(unit)
                name_prefix = "Cell Voltage" if key == 'CELL_VOLTAGES' else "Cell Resistance"
                for i in range(count):
                    sensors.append({
                        'id': f"{key.lower()}_{i + 1}",
                        'name': f"{name_prefix} {i + 1}",
                        'unit': unit,
                        'device_class': dclass,
                        'value_template': f"{{{{ value_json.{key}[{i}] }}}}",
                    })
            else:
                unit = reg.get('unit')
                dclass = class_map.get(unit)
                name = key.replace('_', ' ').title()
                sensors.append({
                    'id': key.lower(),
                    'name': name,
                    'unit': unit,
                    'device_class': dclass,
                    'value_template': f"{{{{ value_json.{key} }}}}",
                })

        # Derived / computed sensors (not in REGISTERS)
        sensors.append({
            'id': 'parsed_alarms',
            'name': 'Active Alarms',
            'value_template': '{{ value_json.parsed_alarms | join(", ") }}'
        })
        sensors.append({
            'id': 'charging_power',
            'name': 'Charging Power',
            'unit': 'W',
            'device_class': 'power',
            'value_template': '{{ value_json.CHARGING_POWER }}'
        })
        sensors.append({
            'id': 'discharging_power',
            'name': 'Discharging Power',
            'unit': 'W',
            'device_class': 'power',
            'value_template': '{{ value_json.DISCHARGING_POWER }}'
        })

        return sensors
