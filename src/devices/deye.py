import struct
import logging
from utils.modbus import BaseModbusClient

logger = logging.getLogger("modbus2mqtt.devices.deye")

# ─────────────────────────────────────────────────────────────────────────────
# DEYE Inverter Modbus Map (SUN-6K-SG05LP1-EU-AM2-P)
# Confirmado con sonda exhaustiva y comparación en vivo
# ─────────────────────────────────────────────────────────────────────────────

REGISTERS = {
    # ── Batería ──────────────────────────────────────────────────────────────
    'BAT_VOLTAGE': {
        'addr': 183, # 0x00B7
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.01,
    },
    'BAT_CURRENT': {
        'addr': 191, # 0x00BF
        'type': 'INT16',
        'unit': 'A',
        'scale': -0.01, # El inversor reporta -3017 para 30.17A de carga (negativo=carga)
    },
    'BAT_POWER': {
        'addr': 190, # 0x00BE
        'type': 'INT16',
        'unit': 'W',
        'scale': -1.0, # El inversor reporta negativo para carga (p.ej. -1674W)
    },
    'BAT_SOC': {
        'addr': 184, # 0x00B8
        'type': 'UINT16',
        'unit': '%',
    },

    # ── Red (Grid) ────────────────────────────────────────────────────────────
    'GRID_VOLTAGE': {
        'addr': 150, # 0x0096
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.1,
    },
    'GRID_POWER': {
        'addr': 169, # 0x00A9
        'type': 'INT16',
        'unit': 'W',
    },
    'GRID_FREQ': {
        'addr': 161, # 0x00A1
        'type': 'UINT16',
        'unit': 'Hz',
        'scale': 0.01,
    },

    # ── Solar (PV) ────────────────────────────────────────────────────────────
    'PV1_VOLTAGE': {
        'addr': 109, # 0x006D
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.1,
    },
    'PV1_POWER': {
        'addr': 186, # 0x00BA
        'type': 'UINT16',
        'unit': 'W',
    },
    'PV2_VOLTAGE': {
        'addr': 111, # 0x006F
        'type': 'UINT16',
        'unit': 'V',
        'scale': 0.1,
    },
    'PV2_CURRENT': {
        'addr': 112, # 0x0070
        'type': 'UINT16',
        'unit': 'A',
        'scale': 0.1,
    },
    'PV2_POWER': {
        'addr': 187, # 0x00BB
        'type': 'UINT16',
        'unit': 'W',
    },

    # ── Consumo (Load) ────────────────────────────────────────────────────────
    'LOAD_POWER': {
        'addr': 178, # 0x00B2
        'type': 'UINT16',
        'unit': 'W',
    },
}

class DeyeClient(BaseModbusClient):
    def get_all_data(self) -> dict:
        data = {}
        mem = {}
        # Lectura en dos bloques para cubrir 100-200
        for start in [100, 150]:
            r = self.read_holding_registers(start, 50)
            if r:
                for i, v in enumerate(r):
                    mem[start + i] = v

        for key, reg in REGISTERS.items():
            addr = reg['addr']
            rtype = reg.get('type', 'UINT16')
            scale = reg.get('scale', 1.0)
            
            v = mem.get(addr)
            if v is None: continue
            
            if rtype == 'INT16':
                val = struct.unpack('>h', struct.pack('>H', v))[0]
            else:
                val = v
            
            data[key] = round(val * scale, 3)
            
        return data

    def get_discovery_sensors(self) -> list:
        sensors = []
        class_map = {
            'V': 'voltage', 'A': 'current', 'W': 'power',
            '°C': 'temperature', '%': 'battery', 'Hz': 'frequency'
        }
        for key, reg in REGISTERS.items():
            unit = reg.get('unit')
            sensors.append({
                'id':             f"deye_{key.lower()}",
                'name':           f"Deye {key.replace('_', ' ').title()}",
                'unit':           unit,
                'device_class':   class_map.get(unit),
                'value_template': f"{{{{ value_json.{key} }}}}",
            })
        return sensors
