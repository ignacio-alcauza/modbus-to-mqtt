import struct
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from utils.modbus import BaseModbusClient

# Placeholder for Deye/Huawei registers
ALL_REGISTER_GROUPS = {}
DEVICE_STATUS_CODES = {}

logger = logging.getLogger("modbus2mqtt.devices.deye")

class HuaweiSUN2000Client(BaseModbusClient):
    """Client for reading Huawei SUN2000 inverter data via Modbus TCP."""

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
                return value / gain if gain != 1 else value

            elif reg_type == "I16":
                value = registers[0]
                if value >= 0x8000:
                    value -= 0x10000
                return value / gain if gain != 1 else value

            elif reg_type == "U32":
                value = (registers[0] << 16) | registers[1]
                return value / gain if gain != 1 else value

            elif reg_type == "I32":
                value = (registers[0] << 16) | registers[1]
                if value >= 0x80000000:
                    value -= 0x100000000
                return value / gain if gain != 1 else value
                
            elif reg_type == "Bitfield32":
                value = (registers[0] << 16) | registers[1]
                bits_map = reg_def.get("bits", {})
                active_bits = []
                for bit_pos, description in bits_map.items():
                    if value & (1 << bit_pos):
                        active_bits.append(description)
                return {
                    "raw": value,
                    "active": active_bits,
                }
                
            elif reg_type == "BitfieldSOC":
                value = registers[0]
                bal_sta = (value >> 8) & 0xFF
                soc = value & 0xFF
                return {
                    "soc": soc,
                    "balance_status": bal_sta,
                }

            elif reg_type == "Bitfield16":
                value = registers[0]
                bits_map = reg_def.get("bits", {})
                active_bits = []
                for bit_pos, description in bits_map.items():
                    if value & (1 << bit_pos):
                        active_bits.append(description)
                return {
                    "raw": value,
                    "active": active_bits,
                }

            else:
                logger.warning("Unknown register type: %s", reg_type)
                return registers

        except Exception as e:
            logger.error(
                "Error decoding %s (type=%s): %s",
                reg_def.get("name", "unknown"),
                reg_type,
                e,
            )
            return None

    def read_block_and_parse(self, base_address: int, count: int, registers_map: List[dict]) -> dict:
        results = {}
        logger.debug("Reading block base: 0x%04X, count: %d", base_address, count)
        block_data = self.read_holding_registers(base_address, count)
            
        if not block_data:
            logger.error("Failed to read block %d", base_address)
            return results

        for reg_def in registers_map:
            name = reg_def["name"]
            offset = reg_def["address"] - base_address
            reg_count = reg_def["count"]

            if offset < 0 or offset + reg_count > len(block_data):
                continue

            raw_registers = block_data[offset : offset + reg_count]
            value = self._decode_value(raw_registers, reg_def)
            
            # Format device statuses
            if name in ["device_status", "inverter_status"] and isinstance(value, int):
                value = {"code": value, "description": DEVICE_STATUS_CODES.get(value, f"Unknown (0x{value:04X})")}
            elif "time" in name.lower() and isinstance(value, (int, float)):
                if value > 0:
                   try:
                       dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
                       value = {"epoch": value, "datetime": dt.strftime("%Y-%m-%d %H:%M:%S UTC")}
                   except Exception:
                       pass

            results[name] = {
                "value": value,
                "unit": reg_def.get("unit", ""),
                "description": reg_def.get("description", ""),
            }

        return results

    def get_all_data(self) -> dict:
        all_data = {}
        all_data['_raw_data'] = {}
        
        # Determine blocks to read based on ALL_REGISTER_GROUPS
        groups = {
            "Equipment Info": {"base": 30000, "count": 81},
            "Power Data": {"base": 32000, "count": 116},
            "Energy Yield": {"base": 32106, "count": 10},
        }

        for group_name, registers in ALL_REGISTER_GROUPS.items():
            if group_name in groups:
                base = groups[group_name]["base"]
                count = groups[group_name]["count"]
                
                block_data = self.read_holding_registers(base, count)
                if block_data:
                    all_data['_raw_data'][group_name] = block_data
                    
                all_data[group_name] = self.read_block_and_parse(base, count, registers)
            else:
                all_data[group_name] = {}
            
            time.sleep(0.1)

        return all_data
