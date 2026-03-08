import struct
import logging
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.jkbms")

# JK BMS PB2A16S20P Modbus TCP Register Map
# Calibrated for PB2A16S20P (16 Cells, 314Ah)

REGISTERS = {
    # --- CELL VOLTAGES ---
    'CELL_VOLTAGES': {
        'addr': 0x1200,
        'count': 16,
        'type': 'UINT16',
        'unit': 'mV',
        'scale': 1.0,
    },

    # --- CELL RESISTANCES ---
    'CELL_RESISTANCES': {
        'addr': 0x1225,
        'count': 16,
        'type': 'UINT16',
        'unit': 'mΩ',
        'scale': 0.001,
    },

    # --- SETTINGS / INFO ---
    'MOS_OTP': { 
        'addr': 0x1230,
        'type': 'UINT16',
        'unit': '°C',
    },

    # --- MONITORING BLOCK ---
    'BAT_VOLTAGE': {
        'addr': 0x1289,
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'BAT_CURRENT': {
        'addr': 0x128A,
        'type': 'INT32_SWAP',
        'count': 2,
        'unit': 'A',
        'scale': 0.001,
    },
    'BAT_POWER': {
        'addr': 0x128C,
        'type': 'INT32_SWAP',
        'count': 2,
        'unit': 'W',
        'scale': 1.0,
    },
    
    # Temperature Probes block 1
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
    
    # Monitoring block 2 (Base 0x1290)
    'SOC_PERCENT': {
        'addr': 0x1293,
        'type': 'UINT16',
        'unit': '%',
    },
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
    'CELL_VOLT_DIFF': {
        'addr': 0x129E, 
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.001,
    },
    'UPTIME': {
        'addr': 0x129E, 
        'type': 'UINT32',
        # Note: Shares high word with CELL_VOLT_DIFF in this firmware
        'count': 2,
    },

    # Temperature Probes block 2 (Base 0x12B0)
    'TEMP_MOS': {
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

    'ALARMS_32BIT': {
        'addr': 0x12A1, 
        'type': 'UINT32_SWAP',
        'count': 2,
        'subtype': 'BITMASK',
    },
    
    # Status Flags
    'CHARGE_ON': {
        'addr': 0x12A0,
        'type': 'UINT8_HIGH',
    },
    'DISCHARGE_ON': {
        'addr': 0x12A0,
        'type': 'UINT8_LOW',
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
        if not registers: return None
        rtype = reg_def.get('type', 'UINT16')
        scale = reg_def.get('scale', 1.0)
        
        if rtype in ['UINT32', 'INT32', 'UINT32_SWAP', 'INT32_SWAP'] and len(registers) < 2:
            return None

        if rtype == 'UINT16': val = registers[0]
        elif rtype == 'INT16': val = struct.unpack('>h', struct.pack('>H', registers[0]))[0]
        elif rtype == 'UINT32': val = (registers[0] << 16) + registers[1]
        elif rtype == 'INT32': val = struct.unpack('>i', struct.pack('>I', (registers[0] << 16) + registers[1]))[0]
        elif rtype == 'UINT32_SWAP': val = (registers[1] << 16) + registers[0]
        elif rtype == 'INT32_SWAP': val = struct.unpack('>i', struct.pack('>I', (registers[1] << 16) + registers[0]))[0]
        elif rtype == 'UINT8_LOW': val = registers[0] & 0xFF
        elif rtype == 'UINT8_HIGH': val = (registers[0] >> 8) & 0xFF
        else: val = registers[0]
        
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
            return f"{months} mes{'es' if months > 1 else ''}{d_str}"
        if days > 0:
            h_str = f", {hours}h" if hours > 0 else ""
            return f"{days} día{'s' if days > 1 else ''}{h_str}"
        
        parts = []
        if hours > 0: parts.append(f"{hours}h")
        if minutes > 0: parts.append(f"{minutes}m")
        if sec > 0 or not parts: parts.append(f"{sec}s")
        return " ".join(parts)

    def get_all_data(self) -> dict:
        data = {}
        # Read standard monitoring and settings block (0x1200 - 0x12BF)
        full_block = []
        for start in [0x1200, 0x1240, 0x1280]:
            chunk = self.read_holding_registers(start, 64)
            full_block.extend(chunk or [0]*64)
            
        for key, reg in REGISTERS.items():
            addr = reg['addr']
            count = reg.get('count', 1)
            offset = addr - 0x1200
            
            if 0 <= offset < len(full_block):
                chunk = full_block[offset : offset + count]
                if key in ['CELL_VOLTAGES', 'CELL_RESISTANCES']:
                    data[key] = [round(v * reg.get('scale', 1.0), 3) for v in chunk]
                else:
                    val = self.decode_value(chunk, reg)
                    if key == 'UPTIME' and val is not None:
                        val = self._format_uptime(val)
                    data[key] = val

        # Alarm Logic
        alarm_val = int(data.get('ALARMS_32BIT', 0))
        alarms = [ALARM_BITS[b] for b in ALARM_BITS if (alarm_val >> b) & 1]
        data['parsed_alarms'] = alarms if alarms else ["Normal"]
        
        # Include raw data for debugging
        data['_raw_data'] = full_block
        
        return data

    def get_discovery_sensors(self) -> list:
        sensors = []
        
        # Mapping unit to HA device_class
        class_map = {
            'V': 'voltage',
            'mV': 'voltage',
            'A': 'current',
            'W': 'power',
            '°C': 'temperature',
            '%': 'battery',
            'Ah': 'energy_storage',
            's': 'duration'
        }
        
        for key, reg in REGISTERS.items():
            if key in ['CELL_VOLTAGES', 'CELL_RESISTANCES']:
                count = reg.get('count', 1)
                unit = reg.get('unit')
                dclass = class_map.get(unit)
                
                name_prefix = "Cell Voltage" if key == 'CELL_VOLTAGES' else "Cell Resistance"
                
                for i in range(count):
                    sensors.append({
                        'id': f"{key.lower()}_{i+1}",
                        'name': f"{name_prefix} {i+1}",
                        'unit': unit,
                        'device_class': dclass,
                        'value_template': f"{{{{ value_json.{key}[{i}] }}}}"
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
                    'value_template': f"{{{{ value_json.{key} }}}}"
                })
        
        # Add parsed_alarms as a generic sensor
        sensors.append({
            'id': 'parsed_alarms',
            'name': 'Active Alarms',
            'value_template': '{{ value_json.parsed_alarms | join(", ") }}'
        })
        
        return sensors
