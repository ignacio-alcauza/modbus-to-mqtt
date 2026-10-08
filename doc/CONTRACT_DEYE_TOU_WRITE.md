# Contrato de ingesta — escritura de Time Of Use (TOU) del Deye

**Estado: implementado en `src/http_api.py` + `DeyeInverterClient.write_tou()`
(`src/devices/deye.py`), 2026-10-08.**

Endpoint HTTP expuesto por el bridge modbus-to-mqtt para que el consumidor
(Pulso) pueda modificar la configuración de Time Of Use del inversor Deye.
Es la contraparte de escritura del bloque de lectura ya documentado en
`doc/PARAMS_CONFIG_DEYE.md` §1 — mismos 5 campos, mismo encoding.

---

## 1. Endpoint

```
POST http://<host-del-bridge>:<puerto>/deye_inverter/tou
Content-Type: application/json
X-Api-Key: <clave compartida — ver .env DEYE_TOU_API_KEY>
```

- Puerto por defecto `9090` (`config.yml` → `deye_inverter.tou_write_api.port`).
  **No es 8090** — verificado en vivo en PRO (2026-10-08) que 8090-8096
  están ocupados por el cluster de contenedores `amz-analytics-*`/`ai-dashboards`.
- El endpoint **solo arranca** si `tou_write_api.active: true` **y** la
  variable de entorno `DEYE_TOU_API_KEY` está definida. Si falta la clave,
  el bridge arranca igual (MQTT/webhook siguen funcionando) pero el
  endpoint de escritura no se levanta — queda escrito como error en el log.
  Nunca hay un endpoint de escritura sin autenticación.
- El bridge corre con `network_mode: host` (ver `docker-compose.yml`), así
  que el puerto en el que se hace `bind()` dentro del contenedor queda
  escuchando directamente en el host — no hace falta (ni tiene efecto)
  añadir un `ports:` al `docker-compose.yml`. Por eso hay que comprobar a
  mano que el puerto está libre en el host antes de fijarlo: un conflicto
  no se detecta en build/deploy, se detecta como "Address already in use"
  al arrancar el proceso.

## 2. Body de la petición

Actualización **parcial**: se puede mandar cualquier subconjunto de estos 5
campos, cada uno como array de **6 elementos** (una franja por posición,
igual que en lectura). Los campos que no se incluyan no se tocan.

```json
{
  "TOU_TIME": ["00:00", "08:00", "10:00", "14:00", "20:00", "22:00"],
  "TOU_POWER": [6000, 6000, 6000, 6000, 6000, 6000],
  "TOU_VOLTAGE": [49.0, 49.0, 49.0, 49.0, 49.0, 49.0],
  "TOU_SOC": [80, 30, 30, 30, 30, 30],
  "TOU_GRID_CHARGE": [true, false, false, false, false, false]
}
```

| Campo | Tipo de elemento | Rango validado | Addr Modbus |
|---|---|---|---|
| `TOU_TIME` | string `"HH:MM"` | `00:00`–`23:59` | 250-255 |
| `TOU_POWER` | entero, W | `0`–`12000` | 256-261 |
| `TOU_VOLTAGE` | float, V | `38.0`–`61.0` | 262-267 |
| `TOU_SOC` | entero, % | `0`–`100` | 268-273 |
| `TOU_GRID_CHARGE` | booleano | `true`/`false` | 274-279 (bit 0, read-modify-write) |

Se rechaza (ver §4): cualquier campo cuyo array no tenga exactamente 6
elementos, con tipo incorrecto, fuera de rango, o una clave que no sea
ninguna de las 5 anteriores. Un body sin ningún campo reconocido también se
rechaza.

## 3. Qué hace el bridge al recibir la petición

No escribe a ciegas. La secuencia, dentro de una única conexión Modbus:

1. **Lee el estado completo del inversor** (los mismos ~40 campos del
   payload normal de MQTT/webhook, no solo TOU) y lo guarda como backup en
   `backups/deye_inverter_tou_<timestamp>_pre.json`.
2. Escribe únicamente los campos TOU incluidos en la petición (FC16, con
   verificación por relectura inmediata de cada campo — ver §6).
3. **Vuelve a leer el estado completo** y lo guarda en
   `backups/deye_inverter_tou_<timestamp>_post.json`.
4. **Compara** el *antes* y el *después*, campo a campo, ignorando:
   - la telemetría en vivo (potencias, corrientes, temperaturas, energía
     acumulada — fluctúan solas, no por esta escritura),
   - los campos TOU que la propia petición pidió cambiar.

   Si algo más cambió (cualquier otro parámetro de configuración, o un
   campo TOU que *no* se pidió tocar), se marca como `unexpected_changes`
   en la respuesta — señal de que la escritura tocó algo que no debía.
5. Responde al consumidor con el resultado de la escritura, el diff, y las
   rutas de los dos backups.

El bridge **no revierte nada automáticamente** si detecta un cambio
inesperado — lo reporta (`unexpected_changes` + log de error) para que se
decida manualmente con los backups a mano, en vez de intentar una
corrección automática sobre un estado ya sorprendente.

## 4. Respuesta

```json
{
  "ok": true,
  "fields": {
    "TOU_POWER": {
      "ok": true,
      "error": null,
      "readback": [6000, 6000, 6000, 6000, 6000, 6000]
    }
  },
  "unexpected_changes": {},
  "backup": {
    "pre": "backups/deye_inverter_tou_20261008T153000123456Z_pre.json",
    "post": "backups/deye_inverter_tou_20261008T153006987654Z_post.json"
  }
}
```

- `fields.<CAMPO>.readback` es el valor **releído del inversor** justo
  después de escribir (mismo encoding que el contrato de lectura) — no el
  valor que se mandó. Así el consumidor confirma que el inversor lo aceptó
  de verdad, no solo que el bridge lo intentó.
- `ok` es `true` solo si **todos** los campos pedidos se escribieron y
  verificaron correctamente **y** `unexpected_changes` está vacío.

| HTTP | Significado |
|---|---|
| `200` | Todo escrito y verificado, sin cambios inesperados |
| `207` | Algún campo falló al escribir, o se detectó un cambio inesperado fuera del TOU, o no se pudo releer el estado completo después de escribir — ver el body para el detalle |
| `400` | Payload inválido (JSON mal formado, campo desconocido, tipo/rango incorrecto, o vacío) |
| `401` | `X-Api-Key` ausente o incorrecta |
| `429` | Petición de escritura hace menos de `min_interval_seconds` desde la anterior (por defecto 5s) — ver §5 |
| `502` | No se pudo conectar al inversor, ni siquiera para la lectura previa (no se escribió nada) |

### 4.1 Error de validación (400)

```json
{
  "ok": false,
  "error": "validation_failed",
  "fields": {
    "TOU_SOC": "each element must be a number between 0 and 100"
  }
}
```

## 5. Por qué hay un rate limit

Estos registros se persisten en la EEPROM/flash del inversor, que tiene un
número de ciclos de escritura limitado — hay reportes de comunidad de
inversores Deye con cuelgues o desgaste de EEPROM por escrituras repetidas
de TOU. El bridge nunca escribe en bucle por su cuenta (esto es siempre a
petición explícita del consumidor), pero aun así aplica un mínimo de
`min_interval_seconds` (configurable, por defecto 5s) entre peticiones de
escritura aceptadas, como salvaguarda ante un consumidor que reintente
agresivamente.

## 6. Notas de implementación

- **Function code: siempre FC16** (`write multiple registers` / `0x10`),
  incluso para un único registro (el caso de `TOU_GRID_CHARGE` por franja).
  **FC06** (`write single register`) se probó en vivo el 2026-10-08 contra
  el inversor real y dio timeout total — el firmware no lo implementa.
- **`TOU_GRID_CHARGE` es read-modify-write.** El registro real (274-279) es
  un bitmask de 3 bits donde solo el bit 0 (grid charge enable) está
  confirmado por prueba activa (ver `doc/PARAMS_CONFIG_DEYE.md` §A.2). Antes
  de escribir se lee el valor actual y solo se cambia el bit 0; los bits
  superiores (significado no confirmado) se preservan tal cual.
- **Un único `threading.Lock` serializa todo el acceso Modbus al Deye** —
  tanto el ciclo de lectura periódico (`query_seconds`) como este endpoint
  comparten el mismo lock, porque la pasarela (Elfin EW11A, WiFi↔RS485)
  solo admite una conexión TCP activa a la vez.
- El valor escrito **no aparece de forma instantánea** en el próximo
  payload de MQTT/webhook — se reflejará en el siguiente ciclo de lectura
  periódico (`query_seconds`, por defecto 10s), igual que un cambio hecho
  desde la app oficial de Deye. La respuesta HTTP de este endpoint ya
  incluye su propia verificación inmediata (`fields.*.readback`), no hace
  falta esperar a MQTT para confirmar la escritura.
- Los backups (`backups/*.json`) no se rotan ni se limpian automáticamente
  — son responsabilidad de operación/despliegue si el volumen crece.
