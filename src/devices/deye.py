import struct
import time
import logging
from typing import Any, List
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.deye")

# ─────────────────────────────────────────────────────────────────────────────
# DEYE Inverter Modbus Map (SUN-6K-SG05LP1-EU-AM2-P)
# Confirmado con sonda exhaustiva y comparación en vivo
# ─────────────────────────────────────────────────────────────────────────────

DEYE_HYBRID_REGISTERS = {
    "Device_Identification": {
        "base": 0,
        "count": 10,
        "registers": [
            {"name": "DEVICE_TYPE", "address": 0, "count": 1, "type": "U16"},
            {"name": "DEVICE_SERIAL", "address": 3, "count": 5, "type": "STR"},
        ]
    },
    "Energy_Data": {
        "base": 60,
        "count": 41,
        "registers": [
            {"name": "DAY_PV_ENERGY", "address": 60, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_PV_ENERGY", "address": 63, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_BATTERY_CHARGE", "address": 72, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_BATTERY_DISCHARGE", "address": 74, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "DAY_GRID_BUY", "address": 76, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "DAY_GRID_SELL", "address": 77, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_GRID_BUY", "address": 78, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_GRID_SELL", "address": 80, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_LOAD_ENERGY", "address": 96, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "GRID_FREQUENCY", "address": 79, "count": 1, "type": "U16", "gain": 100, "unit": "Hz"},
        ]
    },
    "Live_Data_1": {
        "base": 100,
        "count": 55,
        "registers": [
            {"name": "RADIATOR_TEMP", "address": 111, "count": 1, "type": "I16", "gain": 100, "unit": "°C"},
            {"name": "PV1_VOLTAGE", "address": 109, "count": 1, "type": "U16", "gain": 10, "unit": "V"},
            {"name": "PV1_CURRENT", "address": 110, "count": 1, "type": "U16", "gain": 10, "unit": "A"},
            {"name": "PV2_VOLTAGE", "address": 111, "count": 1, "type": "U16", "gain": 10, "unit": "V"},
            {"name": "PV2_CURRENT", "address": 112, "count": 1, "type": "U16", "gain": 10, "unit": "A"},
            {"name": "GRID_L1_VOLTAGE", "address": 150, "count": 1, "type": "U16", "gain": 10, "unit": "V"},
        ]
    },
    "Live_Data_2": {
        "base": 160,
        "count": 40,
        "registers": [
            {"name": "GRID_L1_POWER", "address": 166, "count": 1, "type": "I16", "unit": "W"},
            {"name": "GRID_TOTAL_POWER", "address": 169, "count": 1, "type": "I16", "unit": "W"},
            {"name": "LOAD_L1_POWER", "address": 172, "count": 1, "type": "U16", "unit": "W"},
            {"name": "LOAD_TOTAL_POWER", "address": 175, "count": 1, "type": "U16", "unit": "W"},
            {"name": "BATTERY_TEMP", "address": 182, "count": 1, "type": "I16", "gain": 10, "unit": "°C"},
            {"name": "BATTERY_VOLTAGE", "address": 183, "count": 1, "type": "U16", "gain": 100, "unit": "V"},
            {"name": "BATTERY_SOC", "address": 184, "count": 1, "type": "U16", "unit": "%"},
            {"name": "PV1_POWER", "address": 186, "count": 1, "type": "U16", "unit": "W"},
            {"name": "PV2_POWER", "address": 187, "count": 1, "type": "U16", "unit": "W"},
            {"name": "BATTERY_POWER", "address": 190, "count": 1, "type": "I16", "gain": -1, "unit": "W"},
            {"name": "BATTERY_CURRENT", "address": 191, "count": 1, "type": "I16", "gain": -100, "unit": "A"},
        ]
    }
}

class DeyeInverterClient(BaseModbusClient):
    """Client for reading Deye Hybrid Inverter data via Modbus TCP."""

    def __init__(self, host: str, port: int = 502, unit_id: int = 1, model: str = None, **kwargs):
        super().__init__(host, port, unit_id, **kwargs)
        self.model = model

    def _decode_value(self, registers: List[int], reg_def: dict) -> Any:
        reg_type = reg_def["type"]
        gain = reg_def.get("gain", 1)

        try:
            if reg_type == "STR":
                raw_bytes = b""
                for reg in registers:
                    raw_bytes += struct.pack(">H", reg)
                return raw_bytes.decode("ascii", errors="replace").rstrip("\x00").strip()

            elif reg_type == "U16":
                value = registers[0]
                if value == 0xFFFF: return None
                return round(value / gain, 3) if gain != 1 else value

            elif reg_type == "I16":
                value = registers[0]
                if value == 0x7FFF: return None
                if value >= 0x8000:
                    value -= 0x10000
                return round(value / gain, 3) if gain != 1 else value

            elif reg_type == "U32_LE":
                if len(registers) < 2: return None
                value = (registers[1] << 16) | registers[0]
                if value == 0xFFFFFFFF: return None
                return round(value / gain, 3) if gain != 1 else value

            elif reg_type == "I32":
                if len(registers) < 2: return None
                value = (registers[1] << 16) | registers[0]
                if value == 0x7FFFFFFF: return None
                if value >= 0x80000000:
                    value -= 0x100000000
                return round(value / gain, 3) if gain != 1 else value
                
            else:
                return registers

        except Exception as e:
            logger.error("Error decoding %s: %s", reg_def.get("name", "unknown"), e)
            return None

    def get_all_data(self) -> dict:
        all_data = {}
        all_data['_raw_data'] = {}
        
        if not hasattr(self, '_device_sn'):
            sn_data = self.read_holding_registers(3, 5)
            if sn_data:
                self._device_sn = self._decode_value(sn_data, {"type": "STR"})
            time.sleep(0.1)

        for group_name, group_def in DEYE_HYBRID_REGISTERS.items():
            base = group_def["base"]
            total_count = group_def["count"]
            registers_list = group_def["registers"]
            
            full_block_data = self.read_holding_registers(base, total_count)
            if not full_block_data:
                logger.error("Failed to read group %s", group_name)
                continue
                
            all_data['_raw_data'][group_name] = full_block_data
            
            for reg_def in registers_list:
                name = reg_def["name"]
                offset = reg_def["address"] - base
                reg_count = reg_def.get("count", 1)
                
                if 0 <= offset < len(full_block_data) and offset + reg_count <= len(full_block_data):
                    chunk = full_block_data[offset : offset + reg_count]
                    val = self._decode_value(chunk, reg_def)
                    if val is not None:
                        # Battery temp offset fix (offset 100.0)
                        if name == "BATTERY_TEMP" and val > 100:
                            val = round(val - 100.0, 1)
                        all_data[name] = val
            
            time.sleep(0.1)

        if hasattr(self, '_device_sn'):
            all_data['DEVICE_SN'] = self._device_sn
            
        if self.model:
            all_data['MODEL'] = self.model

        return all_data

    def get_discovery_sensors(self) -> list:
        sensors = []
        class_map = {
            'V': 'voltage',
            'A': 'current',
            'W': 'power',
            '°C': 'temperature',
            '%': 'battery',
            'Hz': 'frequency',
            'kWh': 'energy'
        }
        
        for group in DEYE_HYBRID_REGISTERS.values():
            for reg in group["registers"]:
                name = reg["name"]
                unit = reg.get("unit")
                dclass = class_map.get(unit)
                
                sensors.append({
                    'id': name.lower(),
                    'name': name.replace('_', ' ').title(),
                    'unit': unit,
                    'device_class': dclass,
                    'state_class': 'total_increasing' if unit == 'kWh' else 'measurement',
                    'value_template': f"{{{{ value_json.{name} }}}}"
                })
        
        sensors.append({
            'id': 'model',
            'name': 'Model',
            'value_template': '{{ value_json.MODEL }}'
        })
        
        return sensors
