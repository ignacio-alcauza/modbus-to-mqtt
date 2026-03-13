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

    # ── Voltajes Celdas ×16 (step=2 per-cell, doc oficial) ──────────────────
    'CELL_VOLTAGES': {
        'addr': 0x1200,
        'count': 16,
        'step': 2,      # cada celda ocupa 2 bytes en una palabra de 16 bits
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },

    # ── Resistencias Cables ×16 (empírico: step=1, desde 0x1249) ────────────
    'CELL_RESISTANCES': {
        'addr': 0x1249,
        'count': 16,
        'step': 1,
        'type': 'UINT16',
        'unit': 'mΩ',
        'scale': 0.001,
    },

    # ── Estadísticas de Celdas (doc oficial) ─────────────────────────────────
    'CELL_AVG_VOLTAGE': {
        'addr': 0x1244,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_VOLT_DIFF': {
        'addr': 0x1246,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'CELL_MAX_NO': {
        'addr': 0x1248,
        'type': 'UINT8_HIGH',
    },
    'CELL_MIN_NO': {
        'addr': 0x1248,
        'type': 'UINT8_LOW',
    },

    # ── Temperaturas ──────────────────────────────────────────────────────────
    # Empírico v27: MOS @ 0x1285 = 16.7°C. Doc dice 0x128A pero da 2.2°C (incorrecto).
    'TEMP_MOS': {
        'addr': 0x1285,
        'type': 'INT16',
        'unit': '°C',
        'scale': 0.1,
    },
    # T1 @ 0x1296, T2 @ 0x1297 (empírico v27, confirmados ~14°C)
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

    # ── Voltaje Pack — doc oficial UINT32 @ 0x1290, mV → V ──────────────────
    'BAT_VOLTAGE': {
        'addr': 0x1290,
        'type': 'UINT32',
        'count': 2,
        'unit': 'V',
        'scale': 0.001,
    },

    # ── Corriente — empírico v27: INT32 @ 0x128C, mA → A ────────────────────
    # (doc dice 0x1298 pero en v27 ese registro es siempre 0)
    'BAT_CURRENT': {
        'addr': 0x128C,
        'type': 'INT32',
        'count': 2,
        'unit': 'A',
        'scale': 0.001,
    },

    # ── Balanceo ──────────────────────────────────────────────────────────────
    'BALANCING_CURRENT': {
        'addr': 0x12A4,
        'type': 'INT16',
        'unit': 'A',
        'scale': 0.001,
    },

    # ── SOC — empírico v27: byte bajo de 0x12A3 ──────────────────────────────
    'SOC_PERCENT': {
        'addr': 0x12A3,
        'type': 'UINT8_LOW',
        'unit': '%',
    },
    'BALANCE_STATUS': {
        'addr': 0x12A3,
        'type': 'UINT8_HIGH',
    },

    # ── Capacidades — empírico v27 (offset -8 vs doc) ─────────────────────────
    # SOCCapRemain: INT32 @ 0x129C (doc 0x12A8), mAh → Ah
    'SOC_CAP_REMAIN': {
        'addr': 0x129C,
        'type': 'INT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    # SOCFullChargeCap: UINT32 @ 0x12A6 (confirmado: 314000 mAh = 314 Ah)
    'SOC_FULL_CAP': {
        'addr': 0x12A6,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },
    # SOCCycleCount: UINT32 @ 0x12A8 (doc 0x12B0)
    'CYCLE_COUNT': {
        'addr': 0x12A8,
        'type': 'UINT32',
        'count': 2,
    },
    # SOCCycleCap: UINT32 @ 0x12AA (doc 0x12B4), mAh → Ah
    'TOTAL_CHG_CAPACITY': {
        'addr': 0x12AA,
        'type': 'UINT32',
        'count': 2,
        'unit': 'Ah',
        'scale': 0.001,
    },

    # ── Tiempo operación — empírico: UINT32 @ 0x12AE (doc 0x12BC) ────────────
    'UPTIME': {
        'addr': 0x12AE,
        'type': 'UINT32',
        'count': 2,
    },

    # ── Estado Carga/Descarga — doc 0x12C0 ✅ ─────────────────────────────────
    'CHARGE': {
        'addr': 0x12C0,
        'type': 'UINT8_HIGH',
    },
    'DISCHARGE': {
        'addr': 0x12C0,
        'type': 'UINT8_LOW',
    },

    # ── Alarmas — empírico: UINT32 @ 0x12A0–0x12A1 ───────────────────────────
    'ALARMS_32BIT': {
        'addr': 0x12A0,
        'type': 'UINT32',
        'count': 2,
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
        """Lee todos los bloques de registros necesarios (fragmentos de 16)."""
        data = {}
        # Zona principal 0x1200–0x12CF
        for start in range(0x1200, 0x12D0, 16):
            chunk = self.read_holding_registers(start, 16)
            if chunk:
                for i, v in enumerate(chunk):
                    data[start + i] = v
        # Temperaturas extra 0x12F0–0x12FF
        chunk = self.read_holding_registers(0x12F0, 16)
        if chunk:
            for i, v in enumerate(chunk):
                data[0x12F0 + i] = v
        # Configuración RW 0x1070–0x1088
        chunk = self.read_holding_registers(0x1070, 28)
        if chunk:
            for i, v in enumerate(chunk):
                data[0x1070 + i] = v
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
                        'id':             f"{key.lower()}_{i + 1}",
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
                    'id':             key.lower(),
                    'name':           key.replace('_', ' ').title(),
                    'unit':           unit,
                    'device_class':   class_map.get(unit),
                    'value_template': f"{{{{ value_json.{key} }}}}",
                })

        sensors += [
            {
                'id': 'parsed_alarms', 'name': 'Active Alarms',
                'value_template': '{{ value_json.PARSED_ALARMS | join(", ") }}'
            },
            {
                'id': 'charging_power', 'name': 'Charging Power',
                'unit': 'W', 'device_class': 'power',
                'value_template': '{{ value_json.CHARGING_POWER }}'
            },
            {
                'id': 'discharging_power', 'name': 'Discharging Power',
                'unit': 'W', 'device_class': 'power',
                'value_template': '{{ value_json.DISCHARGING_POWER }}'
            },
        ]
        return sensors
