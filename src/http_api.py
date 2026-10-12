"""
Servidor HTTP de comandos — endpoint de ingesta para que el consumidor
(Pulso) pueda escribir configuración en los dispositivos, empezando por el
Time Of Use (TOU) del Deye. Ver doc/CONTRACT_DEYE_TOU_WRITE.md para el
contrato completo (request/response, validación, por qué el flujo hace
backup + verificación).

No añade dependencias nuevas: usa http.server de la stdlib, igual que
scripts/webhook_receiver.py.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from devices.deye import (
    validate_tou_payload, diff_unexpected_changes,
    validate_grid_charge_payload, compute_grid_charge_suggestion,
)

logger = logging.getLogger("modbus2mqtt.http_api")

BACKUP_DIR = "backups"


def _save_backup(snapshot: dict, suffix: str, prefix: str = "deye_inverter_tou") -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = os.path.join(BACKUP_DIR, f"{prefix}_{ts}_{suffix}.json")
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return path


class DeyeTouRequestHandler(BaseHTTPRequestHandler):
    # Asignados como atributos de clase por start_command_api() antes de
    # servir — un único DeyeInverterClient y un único Lock compartidos con
    # el loop de lectura periódico de main.py (la pasarela Elfin EW11A solo
    # admite una conexión TCP activa a la vez).
    deye_client = None
    deye_lock = None
    api_key = None
    min_interval_seconds = 5

    _last_write_ts = 0.0
    _rate_lock = threading.Lock()

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _check_rate_limit(self) -> bool:
        """El rate limit solo cuenta intentos de escritura ya autenticados y
        validados — una petición rechazada por 401/400 nunca toca el
        inversor, así que no debe consumir la ventana de min_interval_seconds.
        Envía el 429 y devuelve False si no toca aún."""
        with self._rate_lock:
            now = time.time()
            elapsed = now - DeyeTouRequestHandler._last_write_ts
            if elapsed < self.min_interval_seconds:
                self._send_json(429, {
                    "ok": False,
                    "error": "rate_limited",
                    "retry_after_seconds": round(self.min_interval_seconds - elapsed, 1),
                })
                return False
            DeyeTouRequestHandler._last_write_ts = now
            return True

    def do_POST(self):
        route = self.path.rstrip("/")
        if route not in ("/deye_inverter/tou", "/deye_inverter/grid_charge_a"):
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        if not self.api_key or self.headers.get("X-Api-Key") != self.api_key:
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        if route == "/deye_inverter/grid_charge_a":
            requested, errors = validate_grid_charge_payload(payload)
            if errors:
                self._send_json(400, {"ok": False, "error": "validation_failed", "fields": errors})
                return
            # Sin GRID_CHARGE_A = solo consulta: no escribe, no consume rate limit.
            if requested is not None and not self._check_rate_limit():
                return
            self._handle_grid_charge(requested)
            return

        cleaned, errors = validate_tou_payload(payload)
        if errors:
            self._send_json(400, {"ok": False, "error": "validation_failed", "fields": errors})
            return

        if not self._check_rate_limit():
            return

        self._handle_tou_write(cleaned)

    def _handle_grid_charge(self, requested):
        """Lee estado + hora del inversor, calcula la sugerencia y, si hay
        `requested`, escribe GRID_CHARGE_A con backup pre/post y diff."""
        pre_backup_path = post_backup_path = None
        write_result = None
        after = None
        with self.deye_lock:
            try:
                with self.deye_client:
                    before = self.deye_client.get_all_data()
                    now_hhmm = self.deye_client.read_inverter_time() if before else None
                    if not before or now_hhmm is None or before.get("GRID_CHARGE_A") is None:
                        logger.error("GRID_CHARGE_A: no se pudo leer estado/hora del inversor; abortado.")
                        self._send_json(502, {"ok": False, "error": "inverter_unreachable_pre_read"})
                        return

                    previous = before["GRID_CHARGE_A"]
                    max_a = before.get("BATTERY_MAX_CHARGE_A")
                    if requested is not None and max_a is not None and requested > max_a:
                        self._send_json(400, {
                            "ok": False, "error": "validation_failed",
                            "fields": {"GRID_CHARGE_A": f"exceeds BATTERY_MAX_CHARGE_A ({max_a} A)"},
                        })
                        return

                    will_write = requested is not None and requested != previous
                    if will_write:
                        pre_backup_path = _save_backup(before, "pre", "deye_inverter_gridchg")
                        logger.info(f"GRID_CHARGE_A write: backup pre-escritura en {pre_backup_path}")
                        write_result = self.deye_client.write_grid_charge_a(requested)
                        after = self.deye_client.get_all_data()
            except ConnectionError as e:
                logger.error(f"GRID_CHARGE_A: no se pudo conectar al inversor: {e}")
                self._send_json(502, {"ok": False, "error": "inverter_unreachable"})
                return
            except Exception as e:
                logger.error(f"GRID_CHARGE_A: error inesperado: {e}")
                self._send_json(502, {"ok": False, "error": "write_failed", "detail": str(e)})
                return

        # La sugerencia se calcula con el estado leído ANTES de escribir.
        suggestion = compute_grid_charge_suggestion(before, now_hhmm)

        applied = previous
        unexpected = {}
        ok = True
        if write_result is not None:
            applied = write_result["readback"][0] if write_result["readback"] else None
            ok = bool(write_result["ok"])
            if after:
                post_backup_path = _save_backup(after, "post", "deye_inverter_gridchg")
                unexpected = diff_unexpected_changes(before, after, expected_changed={"GRID_CHARGE_A"})
                if unexpected:
                    logger.error(f"GRID_CHARGE_A write: cambios inesperados: {list(unexpected.keys())}")
            else:
                ok = False
                write_result["error"] = write_result.get("error") or "inverter_unreachable_post_read"
            suggestion_applied = applied
        else:
            suggestion_applied = previous

        calc = suggestion.get("calc")
        if calc and suggestion_applied is not None and write_result is not None:
            # Recalcula los indicadores "aplicado vs sugerido" con el valor ya fijado.
            state_after = dict(before, GRID_CHARGE_A=suggestion_applied)
            suggestion = compute_grid_charge_suggestion(state_after, now_hhmm)

        ok = ok and not unexpected
        logger.info(f"GRID_CHARGE_A request: requested={requested} previous={previous} "
                    f"applied={applied} suggested={suggestion.get('suggested_grid_charge_a')} ok={ok}")

        self._send_json(200 if ok else 207, {
            "ok": ok,
            "GRID_CHARGE_A": applied,
            "SUGGESTED_GRID_CHARGE_A": suggestion.get("suggested_grid_charge_a"),
            "write": {
                "requested": requested,
                "previous": previous,
                "written": write_result is not None,
                "ok": None if write_result is None else bool(write_result["ok"]),
                "error": None if write_result is None else write_result.get("error"),
            },
            "suggestion": suggestion,
            "unexpected_changes": unexpected,
            "backup": {"pre": pre_backup_path, "post": post_backup_path},
        })

    def _handle_tou_write(self, cleaned: dict):
        with self.deye_lock:
            try:
                with self.deye_client:
                    before = self.deye_client.get_all_data()
                    if not before:
                        logger.error("TOU write: no se pudo leer el estado completo del inversor antes de escribir; abortado.")
                        self._send_json(502, {"ok": False, "error": "inverter_unreachable_pre_read"})
                        return

                    pre_backup_path = _save_backup(before, "pre")
                    logger.info(f"TOU write: backup pre-escritura guardado en {pre_backup_path}")

                    write_results = self.deye_client.write_tou(cleaned)

                    after = self.deye_client.get_all_data()

            except ConnectionError as e:
                logger.error(f"TOU write: no se pudo conectar al inversor: {e}")
                self._send_json(502, {"ok": False, "error": "inverter_unreachable"})
                return
            except Exception as e:
                logger.error(f"TOU write: error inesperado: {e}")
                self._send_json(502, {"ok": False, "error": "write_failed", "detail": str(e)})
                return

        fields_ok = all(r.get("ok") for r in write_results.values())

        if not after:
            logger.error("TOU write: la escritura se intentó pero no se pudo releer el estado completo después.")
            self._send_json(207, {
                "ok": False,
                "error": "inverter_unreachable_post_read",
                "fields": write_results,
                "backup": {"pre": pre_backup_path, "post": None},
            })
            return

        post_backup_path = _save_backup(after, "post")
        unexpected = diff_unexpected_changes(before, after, expected_changed=set(cleaned.keys()))

        if unexpected:
            logger.error(f"TOU write: cambios inesperados detectados fuera del TOU: {list(unexpected.keys())}")

        all_ok = fields_ok and not unexpected
        status = 200 if all_ok else 207

        logger.info(f"TOU write request: fields={list(cleaned.keys())} fields_ok={fields_ok} unexpected={bool(unexpected)}")

        self._send_json(status, {
            "ok": all_ok,
            "fields": write_results,
            "unexpected_changes": unexpected,
            "backup": {"pre": pre_backup_path, "post": post_backup_path},
        })

    def log_message(self, fmt, *args):
        pass  # logueamos explícitamente arriba; silenciar el access log por defecto


def start_command_api(deye_client, deye_lock, api_key: str, port: int = 9090,
                       min_interval_seconds: int = 5, bind: str = "0.0.0.0"):
    """Arranca el servidor HTTP de comandos en un hilo daemon. No arranca
    (y devuelve None) si falta la api_key — nunca se expone un endpoint de
    escritura sin autenticación."""
    if not api_key:
        logger.error(
            "tou_write_api está activo pero DEYE_TOU_API_KEY no está definida en .env — "
            "el endpoint de escritura TOU NO se ha levantado."
        )
        return None

    DeyeTouRequestHandler.deye_client = deye_client
    DeyeTouRequestHandler.deye_lock = deye_lock
    DeyeTouRequestHandler.api_key = api_key
    DeyeTouRequestHandler.min_interval_seconds = min_interval_seconds

    server = ThreadingHTTPServer((bind, port), DeyeTouRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="deye-tou-api")
    thread.start()
    logger.info(f"Deye TOU write API escuchando en {bind}:{port} (POST /deye_inverter/tou, /deye_inverter/grid_charge_a)")
    return server
