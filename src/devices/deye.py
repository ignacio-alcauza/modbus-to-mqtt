import math
import re
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
    "Status": {
        "base": 59,
        "count": 1,
        "registers": [
            {"name": "INVERTER_STATUS", "address": 59, "count": 1, "type": "U16"},
        ]
    },
    "Energy_Data": {
        "base": 60,
        "count": 41,
        "registers": [
            {"name": "DAY_PV_ENERGY", "address": 60, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_PV_ENERGY", "address": 63, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "DAY_BATTERY_CHARGE", "address": 70, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "DAY_BATTERY_DISCHARGE", "address": 71, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_BATTERY_CHARGE", "address": 72, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_BATTERY_DISCHARGE", "address": 74, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "DAY_GRID_BUY", "address": 76, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "DAY_GRID_SELL", "address": 77, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_GRID_BUY", "address": 78, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_GRID_SELL", "address": 80, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "DAY_LOAD_ENERGY", "address": 84, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "TOTAL_LOAD_ENERGY", "address": 96, "count": 2, "type": "U32_LE", "gain": 10, "unit": "kWh"},
            {"name": "GRID_FREQUENCY", "address": 79, "count": 1, "type": "U16", "gain": 100, "unit": "Hz"},
        ]
    },
    "Live_Data_1": {
        "base": 100,
        "count": 55,
        "registers": [
            {"name": "PV_DAILY_PRODUCTION", "address": 108, "count": 1, "type": "U16", "gain": 10, "unit": "kWh"},
            {"name": "PV2_VOLTAGE", "address": 111, "count": 1, "type": "U16", "gain": 10, "unit": "V"},
            {"name": "PV2_CURRENT", "address": 112, "count": 1, "type": "U16", "gain": 10, "unit": "A"},
            {"name": "RADIATOR_TEMP", "address": 145, "count": 1, "type": "I16", "gain": 10, "unit": "°C"},
            {"name": "GRID_L1_VOLTAGE", "address": 150, "count": 1, "type": "U16", "gain": 10, "unit": "V"},
        ]
    },
    "Live_Data_2": {
        "base": 160,
        "count": 40,
        "registers": [
            {"name": "GRID_L1_POWER", "address": 166, "count": 1, "type": "I16", "unit": "W"},
            {"name": "GRID_TOTAL_POWER", "address": 169, "count": 1, "type": "I16", "unit": "W"},
            {"name": "INVERTER_CURRENT", "address": 164, "count": 1, "type": "U16", "gain": 100, "unit": "A"},
            {"name": "LOAD_L1_POWER", "address": 173, "count": 1, "type": "U16", "unit": "W"},
            {"name": "LOAD_TOTAL_POWER", "address": 175, "count": 1, "type": "U16", "unit": "W"},
            # 173/175 pueden oscilar alrededor de cero y no representan el
            # consumo real de la vivienda; HOUSE_LOAD_POWER (176) sí lo hace,
            # verificado en vivo contra el balance PV2+GRID+BATTERY (±3W).
            {"name": "HOUSE_LOAD_POWER", "address": 176, "count": 1, "type": "U16", "unit": "W", "discovery": False},
            {"name": "BATTERY_TEMP", "address": 182, "count": 1, "type": "I16", "gain": 10, "unit": "°C"},
            {"name": "BATTERY_VOLTAGE", "address": 183, "count": 1, "type": "U16", "gain": 100, "unit": "V"},
            {"name": "BATTERY_SOC", "address": 184, "count": 1, "type": "U16", "unit": "%"},
            {"name": "PV2_POWER", "address": 187, "count": 1, "type": "U16", "unit": "W"},
            {"name": "BATTERY_POWER", "address": 190, "count": 1, "type": "I16", "unit": "W"},
            {"name": "BATTERY_CURRENT", "address": 191, "count": 1, "type": "I16", "gain": 100, "unit": "A"},
            {"name": "GRID_CONNECTED", "address": 194, "count": 1, "type": "U16"},
        ]
    },
    # 200-240: límites y protecciones de batería. Verificado en vivo y cruzado
    # contra doc Modbus oficial monofásico Deye/Sunsynk — ver doc/PARAMS_CONFIG_DEYE.md.
    "Battery_Settings": {
        "base": 200,
        "count": 41,
        "registers": [
            {"name": "BATTERY_CAPACITY_AH", "address": 204, "count": 1, "type": "U16", "unit": "Ah", "discovery": False},
            {"name": "BATTERY_MAX_CHARGE_A", "address": 210, "count": 1, "type": "U16", "unit": "A", "discovery": False},
            {"name": "BATTERY_MAX_DISCHARGE_A", "address": 211, "count": 1, "type": "U16", "unit": "A", "discovery": False},
            {"name": "BATTERY_CONTROL_MODE", "address": 213, "count": 1, "type": "U16", "discovery": False},
            {"name": "BATTERY_RESISTANCE_MOHM", "address": 215, "count": 1, "type": "U16", "unit": "mΩ", "discovery": False},
            {"name": "BATTERY_CHARGE_EFFICIENCY_PCT", "address": 216, "count": 1, "type": "U16", "gain": 10, "unit": "%", "discovery": False},
            {"name": "BATTERY_SHUTDOWN_SOC_PCT", "address": 217, "count": 1, "type": "U16", "unit": "%", "discovery": False},
            {"name": "BATTERY_RESTART_SOC_PCT", "address": 218, "count": 1, "type": "U16", "unit": "%", "discovery": False},
            {"name": "BATTERY_LOWBATT_SOC_PCT", "address": 219, "count": 1, "type": "U16", "unit": "%", "discovery": False},
            {"name": "BATTERY_SHUTDOWN_V", "address": 220, "count": 1, "type": "U16", "gain": 100, "unit": "V", "discovery": False},
            {"name": "BATTERY_RESTART_V", "address": 221, "count": 1, "type": "U16", "gain": 100, "unit": "V", "discovery": False},
            {"name": "BATTERY_LOWBATT_V", "address": 222, "count": 1, "type": "U16", "gain": 100, "unit": "V", "discovery": False},
            # Corriente de carga desde red (Battery Setting-3). Escribible vía
            # FC16 (verificado en vivo 2026-10-12). Solo se envía al webhook,
            # no al topic MQTT — ver WEBHOOK_ONLY_FIELDS.
            {"name": "GRID_CHARGE_A", "address": 230, "count": 1, "type": "U16", "unit": "A", "discovery": False},
        ]
    },
    # 243-279: modo de trabajo + horario Time of Use completo. Los campos
    # escalares van por el mecanismo genérico; el bloque TOU (250-279) se
    # ensambla en arrays de 6 directamente en get_all_data() — ver ahí.
    "Settings": {
        "base": 243,
        "count": 37,
        "registers": [
            {"name": "PRIORITY_LOAD", "address": 243, "count": 1, "type": "U16"},
            {"name": "ENERGY_PATTERN", "address": 243, "count": 1, "type": "U16", "discovery": False},
            {"name": "WORK_MODE", "address": 244, "count": 1, "type": "U16", "discovery": False},
            {"name": "MAX_SELL_POWER", "address": 245, "count": 1, "type": "U16", "unit": "W", "discovery": False},
            {"name": "SOLAR_SELL", "address": 247, "count": 1, "type": "U16", "discovery": False},
            {"name": "USE_TIMER",     "address": 248, "count": 1, "type": "U16"},
        ]
    }
}

WORK_MODE_TEXT = {0: "SellingFirst", 1: "ZeroExportToLoad", 2: "ZeroExportToCT"}
ENERGY_PATTERN_TEXT = {0: "BatteryPriority", 1: "LoadFirst"}
BATTERY_CONTROL_MODE_TEXT = {0: "ByVoltage", 1: "BySOC", 2: "NoBattery"}

# Campos que viajan solo al webhook y se eliminan del payload MQTT/HA.
WEBHOOK_ONLY_FIELDS = {"GRID_CHARGE_A"}

# ─────────────────────────────────────────────────────────────────────────────
# Escritura de Time Of Use (TOU) — contrato de ingesta para el consumidor.
# Direcciones ya verificadas en lectura (ver doc/PARAMS_CONFIG_DEYE.md §A.1-2).
# Escritura confirmada en vivo el 2026-10-08: el inversor solo implementa
# FC16 (write multiple registers) — FC06 (single) da timeout, no lo soporta.
# ─────────────────────────────────────────────────────────────────────────────

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# base addr + rango de validación por campo. TOU_TIME y TOU_GRID_CHARGE no
# llevan min/max porque su validación es de formato (HH:MM / booleano), no
# numérica.
TOU_FIELD_SPECS = {
    "TOU_TIME":        {"base": 250},
    "TOU_POWER":       {"base": 256, "min": 0,    "max": 12000},
    "TOU_VOLTAGE":     {"base": 262, "min": 38.0, "max": 61.0},
    "TOU_SOC":         {"base": 268, "min": 0,    "max": 100},
    "TOU_GRID_CHARGE": {"base": 274},
}

# Grupos de telemetría en vivo: fluctúan solo por el paso del tiempo, nunca
# por una escritura de TOU. Se excluyen de la comprobación "solo ha cambiado
# el TOU" en write_tou_with_full_verification() para no generar falsos
# positivos en cada ciclo.
_LIVE_TELEMETRY_GROUPS = {"Status", "Energy_Data", "Live_Data_1", "Live_Data_2"}


def _live_telemetry_field_names() -> set:
    names = set()
    for group_name, group_def in DEYE_HYBRID_REGISTERS.items():
        if group_name in _LIVE_TELEMETRY_GROUPS:
            for reg in group_def["registers"]:
                names.add(reg["name"])
    return names


LIVE_TELEMETRY_FIELDS = _live_telemetry_field_names()


def validate_tou_payload(payload: dict):
    """Valida un payload de escritura TOU (parcial: cualquier subconjunto de
    los 5 campos). Devuelve (cleaned, errors):
      - cleaned: dict solo con los campos que pasaron validación, valores
        tal cual los mandó el consumidor (sin codificar a registros Modbus).
      - errors: dict campo -> mensaje de error. Si hay errors, cleaned debe
        descartarse entero (no se escribe nada parcialmente válido).
    """
    if not isinstance(payload, dict):
        return {}, {"_payload": "body must be a JSON object"}

    errors = {}
    unknown = sorted(set(payload.keys()) - set(TOU_FIELD_SPECS.keys()))
    if unknown:
        errors["_unknown_fields"] = unknown

    cleaned = {}
    for name, spec in TOU_FIELD_SPECS.items():
        if name not in payload:
            continue
        value = payload[name]
        if not isinstance(value, list) or len(value) != 6:
            errors[name] = "must be an array of exactly 6 elements"
            continue

        if name == "TOU_TIME":
            if all(isinstance(v, str) and _HHMM_RE.match(v) for v in value):
                cleaned[name] = value
            else:
                errors[name] = "each element must be 'HH:MM' (00:00-23:59)"

        elif name == "TOU_GRID_CHARGE":
            if all(isinstance(v, bool) for v in value):
                cleaned[name] = value
            else:
                errors[name] = "each element must be true/false"

        else:  # TOU_POWER, TOU_VOLTAGE, TOU_SOC — numéricos con rango
            lo, hi = spec["min"], spec["max"]
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi for v in value):
                cleaned[name] = value
            else:
                errors[name] = f"each element must be a number between {lo} and {hi}"

    if not cleaned and not errors:
        errors["_payload"] = (
            "at least one of TOU_TIME, TOU_POWER, TOU_VOLTAGE, TOU_SOC, "
            "TOU_GRID_CHARGE is required"
        )

    return cleaned, errors


# ─────────────────────────────────────────────────────────────────────────────
# Escritura de GRID_CHARGE_A (reg 230) + cálculo de corriente sugerida.
# Contrato: doc/CONTRACT_DEYE_GRID_CHARGE_A.md
# ─────────────────────────────────────────────────────────────────────────────

GRID_CHARGE_A_ADDR = 230
GRID_CHARGE_A_MIN = 1
GRID_CHARGE_A_MAX = 185

# Registros de reloj del inversor (hora local del propio inversor, la misma
# con la que se evalúan las franjas TOU): 22=(año-2000)<<8|mes,
# 23=día<<8|hora, 24=minuto<<8|segundo. Verificado en vivo 2026-10-12.
INVERTER_CLOCK_ADDR = 22

# Margen sobre la corriente mínima teórica: cubre la reducción de corriente
# del BMS cerca del tope de SoC, balanceo y pérdidas no modeladas.
SUGGESTION_SAFETY_MARGIN = 1.25
SUGGESTION_MIN_A = 5


def validate_grid_charge_payload(payload: dict):
    """Devuelve (requested, errors). `requested` es None si el body no trae
    GRID_CHARGE_A (modo solo-consulta: calcula la sugerencia sin escribir)."""
    if not isinstance(payload, dict):
        return None, {"_payload": "body must be a JSON object"}

    errors = {}
    unknown = sorted(set(payload.keys()) - {"GRID_CHARGE_A"})
    if unknown:
        errors["_unknown_fields"] = unknown

    requested = None
    if "GRID_CHARGE_A" in payload:
        v = payload["GRID_CHARGE_A"]
        if isinstance(v, bool) or not isinstance(v, int) or not (GRID_CHARGE_A_MIN <= v <= GRID_CHARGE_A_MAX):
            errors["GRID_CHARGE_A"] = f"must be an integer between {GRID_CHARGE_A_MIN} and {GRID_CHARGE_A_MAX}"
        else:
            requested = v
    return requested, errors


def compute_grid_charge_suggestion(state: dict, now_hhmm: tuple) -> dict:
    """Calcula la corriente de carga desde red necesaria para llegar al SoC
    objetivo de la franja TOU con carga de red, a partir de un snapshot de
    get_all_data() y la hora del inversor (h, m). Función pura, sin I/O.
    Metodología: doc/CONTRACT_DEYE_GRID_CHARGE_A.md §4.
    """
    now_min = now_hhmm[0] * 60 + now_hhmm[1]
    times = state.get("TOU_TIME")
    gc_flags = state.get("TOU_GRID_CHARGE")
    soc_targets = state.get("TOU_SOC")
    result = {"status": None, "suggested_grid_charge_a": None, "slot": None,
              "inputs": None, "calc": None, "warnings": []}

    if not (times and gc_flags and soc_targets):
        result["status"] = "tou_unavailable"
        return result

    starts = [int(t[:2]) * 60 + int(t[3:]) for t in times]
    n = len(starts)
    slots = []
    for i in range(n):
        dur = (starts[(i + 1) % n] - starts[i]) % 1440 or 1440
        elapsed = (now_min - starts[i]) % 1440
        slots.append({"index": i, "start": times[i], "end": times[(i + 1) % n],
                      "duration_min": dur, "active": elapsed < dur,
                      "elapsed_min": elapsed, "starts_in_min": (starts[i] - now_min) % 1440})

    charge_slots = [s for s in slots if gc_flags[s["index"]]]
    if not charge_slots:
        result["status"] = "no_grid_charge_slot"
        return result

    active = [s for s in charge_slots if s["active"]]
    if active:
        slot = active[0]
        remaining_min = slot["duration_min"] - slot["elapsed_min"]
    else:
        slot = min(charge_slots, key=lambda s: s["starts_in_min"])
        remaining_min = slot["duration_min"]

    idx = slot["index"]
    target = soc_targets[idx]
    soc = state.get("BATTERY_SOC")
    cap_ah = state.get("BATTERY_CAPACITY_AH")
    volt = state.get("BATTERY_VOLTAGE")
    max_a = state.get("BATTERY_MAX_CHARGE_A")
    eff = (state.get("BATTERY_CHARGE_EFFICIENCY_PCT") or 99.0) / 100
    applied = state.get("GRID_CHARGE_A")

    result["slot"] = {"index": idx, "start": slot["start"], "end": slot["end"],
                      "active_now": slot["active"], "remaining_min": remaining_min,
                      "starts_in_min": None if slot["active"] else slot["starts_in_min"],
                      "target_soc_pct": target}
    result["inputs"] = {"inverter_time": f"{now_hhmm[0]:02d}:{now_hhmm[1]:02d}",
                        "battery_soc_pct": soc, "battery_capacity_ah": cap_ah,
                        "battery_voltage_v": volt, "battery_max_charge_a": max_a,
                        "charge_efficiency": eff, "house_load_power_w": state.get("HOUSE_LOAD_POWER"),
                        "tou_power_w": (state.get("TOU_POWER") or [None] * n)[idx],
                        "safety_margin": SUGGESTION_SAFETY_MARGIN}

    if None in (soc, cap_ah, volt, max_a):
        result["status"] = "inputs_unavailable"
        return result

    # Franja aún no iniciada: el SoC bajará hasta el inicio. Se calcula con el
    # peor caso razonable: el menor entre el SoC actual y el SoC mínimo
    # configurado en las franjas sin carga de red (el suelo al que baja de noche).
    soc_for_calc = soc
    if not slot["active"]:
        floors = [v for i, v in enumerate(soc_targets) if not gc_flags[i]]
        if floors and min(floors) < soc:
            soc_for_calc = min(floors)
            result["warnings"].append(
                f"slot has not started; calculated assuming start SoC {soc_for_calc}% "
                f"(lowest TOU_SOC of non-grid-charge slots) instead of current {soc}%")
    result["inputs"]["assumed_start_soc_pct"] = soc_for_calc

    missing_pct = target - soc_for_calc
    if missing_pct <= 0:
        result["status"] = "target_reached"
        result["calc"] = {"missing_pct": 0}
        return result

    needed_ah = missing_pct / 100 * cap_ah / eff
    hours = max(remaining_min, 1) / 60
    min_a = needed_ah / hours
    suggested = max(SUGGESTION_MIN_A, math.ceil(min_a * SUGGESTION_SAFETY_MARGIN))
    feasible = min_a <= max_a
    if suggested > max_a:
        suggested = max_a
        result["warnings"].append(
            f"required current exceeds BATTERY_MAX_CHARGE_A ({max_a} A); suggestion capped"
            if not feasible else "margin-adjusted suggestion capped at BATTERY_MAX_CHARGE_A")

    tou_power = result["inputs"]["tou_power_w"]
    if tou_power is not None and suggested * volt > tou_power:
        result["warnings"].append(
            f"suggested charge power (~{round(suggested * volt)} W) exceeds TOU_POWER of the slot ({tou_power} W)")

    projected = None
    if applied is not None:
        projected = min(100.0, round(soc_for_calc + applied * eff * hours / cap_ah * 100, 1))

    result["calc"] = {"missing_pct": round(missing_pct, 1), "needed_ah": round(needed_ah, 1),
                      "remaining_hours": round(hours, 2), "min_current_a": round(min_a, 1),
                      "feasible": feasible,
                      "applied_meets_minimum": None if applied is None else applied >= math.ceil(min_a),
                      "applied_meets_suggested": None if applied is None else applied >= suggested,
                      "projected_soc_at_slot_end_pct": projected}
    result["status"] = "ok" if feasible else "infeasible"
    result["suggested_grid_charge_a"] = suggested
    return result


def diff_unexpected_changes(before: dict, after: dict, expected_changed: set) -> dict:
    """Compara dos snapshots de get_all_data() e ignora: _raw_data, los campos
    de telemetría en vivo (fluctúan solos) y los campos que el propio
    consumidor pidió cambiar. Lo que quede y sea distinto es una señal de que
    la escritura tocó algo que no debía — ver §A.6/§2 de
    doc/CONTRACT_DEYE_TOU_WRITE.md.
    """
    keys = (set(before.keys()) | set(after.keys()))
    keys -= {"_raw_data"}
    keys -= LIVE_TELEMETRY_FIELDS
    keys -= expected_changed

    unexpected = {}
    for key in keys:
        if before.get(key) != after.get(key):
            unexpected[key] = {"before": before.get(key), "after": after.get(key)}
    return unexpected


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
                        if name in ("BATTERY_TEMP", "RADIATOR_TEMP") and val > 100:
                            val = round(val - 100.0, 1)
                        all_data[name] = val

            # Bloque TOU (250-279): 6 franjas horarias, ensambladas como
            # arrays directamente desde full_block_data (no vía registers[]).
            # Verificado en vivo, ver doc/PARAMS_CONFIG_DEYE.md §1-2.
            if group_name == "Settings":
                def _word(addr):
                    off = addr - base
                    return full_block_data[off] if 0 <= off < len(full_block_data) else None

                raw_times = [_word(250 + i) for i in range(6)]
                raw_power = [_word(256 + i) for i in range(6)]
                raw_voltage = [_word(262 + i) for i in range(6)]
                raw_soc = [_word(268 + i) for i in range(6)]
                raw_gridcharge = [_word(274 + i) for i in range(6)]

                if all(v is not None for v in raw_times):
                    all_data["TOU_TIME"] = [f"{v // 100:02d}:{v % 100:02d}" for v in raw_times]
                if all(v is not None for v in raw_power):
                    all_data["TOU_POWER"] = raw_power
                if all(v is not None for v in raw_voltage):
                    all_data["TOU_VOLTAGE"] = [round(v / 100, 2) for v in raw_voltage]
                if all(v is not None for v in raw_soc):
                    all_data["TOU_SOC"] = raw_soc
                if all(v is not None for v in raw_gridcharge):
                    # bit 0 = Grid Charge enable, confirmado por prueba activa
                    # (ver doc/PARAMS_CONFIG_DEYE.md §2): 4=OFF, 5=ON.
                    all_data["TOU_GRID_CHARGE"] = [bool(v & 1) for v in raw_gridcharge]

            time.sleep(0.1)

        # Texto legible para los enums de configuración (raw + *_TEXT, mismo
        # patrón que ALARMS_DECODED/BALAN_STA_TEXT del JK BMS)
        if "WORK_MODE" in all_data:
            all_data["WORK_MODE_TEXT"] = WORK_MODE_TEXT.get(all_data["WORK_MODE"], "Unknown")
        if "ENERGY_PATTERN" in all_data:
            all_data["ENERGY_PATTERN_TEXT"] = ENERGY_PATTERN_TEXT.get(all_data["ENERGY_PATTERN"], "Unknown")
        if "BATTERY_CONTROL_MODE" in all_data:
            all_data["BATTERY_CONTROL_MODE_TEXT"] = BATTERY_CONTROL_MODE_TEXT.get(all_data["BATTERY_CONTROL_MODE"], "Unknown")

        if hasattr(self, '_device_sn'):
            all_data['DEVICE_SN'] = self._device_sn
            
        if self.model:
            all_data['MODEL'] = self.model

        return all_data

    def _write_contiguous(self, base_addr: int, raw_values: List[int]) -> dict:
        """Escribe un bloque contiguo vía FC16 y relee para verificar. Debe
        llamarse dentro de una conexión abierta (`with client:`)."""
        ok = self.write_registers(base_addr, raw_values)
        if not ok:
            return {"ok": False, "error": "modbus_write_failed", "readback": None}

        readback = self.read_holding_registers(base_addr, len(raw_values))
        if readback is None:
            return {"ok": False, "error": "modbus_readback_failed", "readback": None}

        return {"ok": readback == raw_values, "error": None, "readback": readback}

    def write_tou(self, fields: dict) -> dict:
        """Escribe una actualización parcial de TOU. `fields` debe venir ya
        validado por validate_tou_payload() — valores tal cual los ve el
        consumidor (strings "HH:MM", voltios, booleanos), no codificados.
        Debe llamarse dentro de una conexión abierta (`with client:`).
        Devuelve {campo: {"ok", "error", "readback"}} — readback ya
        decodificado al mismo formato que el contrato de lectura.
        """
        results = {}

        if "TOU_TIME" in fields:
            raw = [int(h) * 100 + int(m) for h, m in (s.split(":") for s in fields["TOU_TIME"])]
            r = self._write_contiguous(TOU_FIELD_SPECS["TOU_TIME"]["base"], raw)
            if r["readback"] is not None:
                r["readback"] = [f"{v // 100:02d}:{v % 100:02d}" for v in r["readback"]]
            results["TOU_TIME"] = r

        if "TOU_POWER" in fields:
            raw = [int(v) for v in fields["TOU_POWER"]]
            results["TOU_POWER"] = self._write_contiguous(TOU_FIELD_SPECS["TOU_POWER"]["base"], raw)

        if "TOU_VOLTAGE" in fields:
            raw = [round(v * 100) for v in fields["TOU_VOLTAGE"]]
            r = self._write_contiguous(TOU_FIELD_SPECS["TOU_VOLTAGE"]["base"], raw)
            if r["readback"] is not None:
                r["readback"] = [round(v / 100, 2) for v in r["readback"]]
            results["TOU_VOLTAGE"] = r

        if "TOU_SOC" in fields:
            raw = [int(v) for v in fields["TOU_SOC"]]
            results["TOU_SOC"] = self._write_contiguous(TOU_FIELD_SPECS["TOU_SOC"]["base"], raw)

        if "TOU_GRID_CHARGE" in fields:
            base = TOU_FIELD_SPECS["TOU_GRID_CHARGE"]["base"]
            # Read-modify-write: bit0 es grid charge enable (confirmado por
            # prueba activa, ver doc/PARAMS_CONFIG_DEYE.md §A.2); los bits
            # superiores no están identificados y no se tocan.
            current = self.read_holding_registers(base, 6)
            if current is None:
                results["TOU_GRID_CHARGE"] = {"ok": False, "error": "modbus_read_before_write_failed", "readback": None}
            else:
                new_values = [(cur & ~1) | (1 if en else 0) for cur, en in zip(current, fields["TOU_GRID_CHARGE"])]
                ok = self.write_registers(base, new_values)
                if not ok:
                    results["TOU_GRID_CHARGE"] = {"ok": False, "error": "modbus_write_failed", "readback": None}
                else:
                    readback = self.read_holding_registers(base, 6)
                    if readback is None:
                        results["TOU_GRID_CHARGE"] = {"ok": False, "error": "modbus_readback_failed", "readback": None}
                    else:
                        decoded = [bool(v & 1) for v in readback]
                        results["TOU_GRID_CHARGE"] = {
                            "ok": decoded == fields["TOU_GRID_CHARGE"],
                            "error": None,
                            "readback": decoded,
                        }

        return results

    def read_inverter_time(self):
        """Hora local (h, m) del reloj del inversor, o None si falla."""
        regs = self.read_holding_registers(INVERTER_CLOCK_ADDR, 3)
        if not regs:
            return None
        hour, minute = regs[1] & 0xFF, regs[2] >> 8
        if hour > 23 or minute > 59:
            return None
        return hour, minute

    def write_grid_charge_a(self, value: int) -> dict:
        """Escribe GRID_CHARGE_A (reg 230, FC16) y relee. Dentro de `with client:`."""
        return self._write_contiguous(GRID_CHARGE_A_ADDR, [int(value)])

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
        
        # Registers handled as binary_sensor (excluded from auto sensor loop)
        binary_sensor_names = {"GRID_CONNECTED", "PRIORITY_LOAD", "USE_TIMER"}

        for group in DEYE_HYBRID_REGISTERS.values():
            for reg in group["registers"]:
                name = reg["name"]
                if name in binary_sensor_names:
                    continue
                if not reg.get("discovery", True):
                    continue
                unit = reg.get("unit")
                dclass = class_map.get(unit)
                
                sensor = {
                    'id':             f"deye_{name.lower()}",
                    'name':           name.replace('_', ' ').title(),
                    'unit':           unit,
                    'device_class':   dclass,
                    'value_template': f"{{{{ value_json.{name} | int }}}}" if name == 'BATTERY_SOC' else f"{{{{ value_json.{name} }}}}"
                }
                if unit:
                    sensor['state_class'] = 'total_increasing' if unit == 'kWh' else 'measurement'
                
                sensors.append(sensor)
        
        sensors.append({
            'id': 'deye_grid_connected',
            'name': 'Grid Connected',
            'component': 'binary_sensor',
            'device_class': 'connectivity',
            'value_template': '{{ value_json.GRID_CONNECTED }}',
            'payload_on': 1,
            'payload_off': 0,
        })
        sensors.append({
            'id': 'deye_priority_load',
            'name': 'Priority Load',
            'component': 'binary_sensor',
            'value_template': '{{ value_json.PRIORITY_LOAD }}',
            'payload_on': 1,
            'payload_off': 0,
        })
        sensors.append({
            'id': 'deye_use_timer',
            'name': 'Use Timer',
            'component': 'binary_sensor',
            'value_template': '{{ value_json.USE_TIMER }}',
            'payload_on': 255,
            'payload_off': 0,
        })

        sensors.append({
            'id': 'model',
            'name': 'Model',
            'value_template': '{{ value_json.MODEL }}'
        })
        
        return sensors
