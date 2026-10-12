# Contrato — corriente de carga desde red (`GRID_CHARGE_A`) del Deye

**Estado: implementado (2026-10-12)** en `src/http_api.py` +
`DeyeInverterClient.write_grid_charge_a()` / `compute_grid_charge_suggestion()`
(`src/devices/deye.py`). Escritura verificada en vivo contra el inversor real.

Para el consumidor (Pulso): este endpoint (a) fija la **corriente máxima con
la que el inversor carga la batería desde la red** y (b) devuelve siempre un
**valor sugerido** calculado con el estado real de la batería para garantizar
que se alcanza el SoC objetivo de la franja TOU nocturna.

---

## 1. Contexto: por qué existe

El TOU permite fijar un SoC objetivo por franja (`TOU_SOC`) con carga de red
(`TOU_GRID_CHARGE`). Pero la **velocidad** de esa carga la limita
`GRID_CHARGE_A` (registro Modbus 230, "Grid Charge current", valor de fábrica
típico 18 A ≈ 0,9 kW). Con 18 A en 8 h no se llega del 25 % al 80 % en una
batería de 314 Ah. `TOU_POWER` (W) y `BATTERY_MAX_CHARGE_A` (reg 210) son
otros límites, pero en esta instalación ya están muy por encima (6000 W / 120 A).

## 2. Lectura: campo `GRID_CHARGE_A` en el webhook

- Campo nuevo en el JSON de estado del Deye: `"GRID_CHARGE_A": 18` (entero,
  **amperios**, corriente de carga de batería desde red).
- **Solo viaja por el webhook** (`/api/v1/ingest`). **No se publica en MQTT ni
  en Home Assistant** (no hay sensor de discovery y se elimina del payload del
  topic `deye_inverter/state`).
- Se refresca en cada ciclo de lectura (`query_seconds`, 10 s). Tras una
  escritura, el nuevo valor aparece en el siguiente ciclo.
- Confianza: máxima (leído y escrito en vivo). No requiere `schema_version` nuevo
  (campo añadido, ninguno renombrado).

## 3. Endpoint

```
POST http://<host-del-bridge>:9090/deye_inverter/grid_charge_a
Content-Type: application/json
X-Api-Key: <la misma clave que el endpoint TOU — .env DEYE_TOU_API_KEY>
```

Mismo servidor, puerto, clave, `Lock` Modbus y activación
(`deye_inverter.tou_write_api.active`) que `POST /deye_inverter/tou` (ver
`CONTRACT_DEYE_TOU_WRITE.md` §1). No requiere configuración nueva.

### 3.1 Body

| Body | Comportamiento |
|---|---|
| `{"GRID_CHARGE_A": 40}` | Escribe 40 A **y** devuelve la sugerencia |
| `{}` (o sin body) | **Solo consulta**: no escribe, no consume rate limit, devuelve el valor actual y la sugerencia |

- `GRID_CHARGE_A`: **entero** (no float, no string, no bool), **1–185** A.
  Para desactivar la carga de red usar `TOU_GRID_CHARGE` por franja, no `0`.
- Además de la validación estática, si el valor supera el
  `BATTERY_MAX_CHARGE_A` real del inversor (reg 210, hoy 120 A) se rechaza
  con 400 sin escribir.
- Cualquier otra clave en el body → 400 (`_unknown_fields`).
- **Idempotencia / desgaste de flash:** si el valor pedido es igual al que ya
  tiene el inversor, **no se escribe** (`write.written=false`) y se responde
  200. Es seguro llamar al endpoint periódicamente con el valor sugerido.

### 3.2 Flujo interno

1. Lee el estado completo del inversor y su **reloj interno** (regs 22–24).
2. Si hay valor pedido y distinto del actual: backup
   `backups/deye_inverter_gridchg_<ts>_pre.json` → escribe reg 230 (FC16) →
   relee → vuelve a leer el estado completo → backup `_post.json` → compara
   antes/después (`unexpected_changes`, igual que el TOU).
3. Calcula la sugerencia (§4) con el estado leído **antes** de escribir y
   recalcula los indicadores `applied_*` con el valor ya fijado.
4. No revierte nada automáticamente.

### 3.3 Respuesta (200 / 207)

```json
{
  "ok": true,
  "GRID_CHARGE_A": 40,
  "SUGGESTED_GRID_CHARGE_A": 28,
  "write": {
    "requested": 40, "previous": 18,
    "written": true, "ok": true, "error": null
  },
  "suggestion": {
    "status": "ok",
    "suggested_grid_charge_a": 28,
    "slot": {
      "index": 0, "start": "00:00", "end": "08:00",
      "active_now": true, "remaining_min": 480, "starts_in_min": null,
      "target_soc_pct": 80
    },
    "inputs": {
      "inverter_time": "00:00", "battery_soc_pct": 25,
      "assumed_start_soc_pct": 25, "battery_capacity_ah": 314,
      "battery_voltage_v": 51.2, "battery_max_charge_a": 120,
      "charge_efficiency": 0.99, "house_load_power_w": 400,
      "tou_power_w": 6000, "safety_margin": 1.25
    },
    "calc": {
      "missing_pct": 55.0, "needed_ah": 174.4, "remaining_hours": 8.0,
      "min_current_a": 21.8, "feasible": true,
      "applied_meets_minimum": true, "applied_meets_suggested": true,
      "projected_soc_at_slot_end_pct": 100.0
    },
    "warnings": []
  },
  "unexpected_changes": {},
  "backup": {"pre": "backups/deye_inverter_gridchg_…_pre.json", "post": "backups/deye_inverter_gridchg_…_post.json"}
}
```

Campos principales para el consumidor:

- **`GRID_CHARGE_A`**: valor **fijado en el inversor** tras la operación
  (releído del registro si hubo escritura; el actual si no la hubo).
- **`SUGGESTED_GRID_CHARGE_A`**: valor recomendado (A) para alcanzar el SoC
  objetivo (§4). `null` si no hay sugerencia (ver `suggestion.status`).
- `suggestion.calc.applied_meets_minimum`: ¿el valor fijado basta, en teoría, para
  llegar al objetivo? `applied_meets_suggested`: ¿cumple además el margen de seguridad?
- `suggestion.calc.projected_soc_at_slot_end_pct`: SoC estimado al final de la franja
  con el valor fijado (ideal, sin reducción por BMS; tope 100).

`suggestion.status`:

| status | Significado | `suggested_grid_charge_a` |
|---|---|---|
| `ok` | Calculado, alcanzable | entero (A) |
| `infeasible` | Ni con `BATTERY_MAX_CHARGE_A` se llega al objetivo en el tiempo restante; se devuelve el tope | `BATTERY_MAX_CHARGE_A` |
| `target_reached` | El SoC ya ≥ objetivo; no hace falta cambiar nada | `null` |
| `no_grid_charge_slot` | Ninguna franja tiene `TOU_GRID_CHARGE=true` | `null` |
| `inputs_unavailable` / `tou_unavailable` | Faltan datos en la lectura del inversor | `null` |

### 3.4 Códigos HTTP

| HTTP | Significado |
|---|---|
| `200` | Escrito (o no necesario) y verificado; sin cambios inesperados |
| `207` | Fallo de escritura/verificación, relectura posterior imposible, o `unexpected_changes` no vacío |
| `400` | Validación (JSON inválido, tipo/rango, clave desconocida, o > `BATTERY_MAX_CHARGE_A`) |
| `401` | `X-Api-Key` ausente o incorrecta |
| `429` | Escritura demasiado pronto; `min_interval_seconds` (5 s) **compartido** con el endpoint TOU. Las consultas `{}` no cuentan |
| `502` | Inversor inaccesible o sin lectura de estado/reloj; no se escribió nada |

## 4. Cálculo del valor sugerido

Objetivo: la corriente **mínima constante** que, durante el tiempo que queda
de la franja, lleva la batería del SoC actual al `TOU_SOC` de la franja, más
un margen.

**4.1 Franja objetivo.** De `TOU_TIME`/`TOU_GRID_CHARGE`: la franja `i` va de
`TOU_TIME[i]` a `TOU_TIME[i+1]` (la última cierra en `TOU_TIME[0]`, cíclico).
Se elige, entre las que tienen `TOU_GRID_CHARGE=true`, la que está **activa
ahora** (según el **reloj del inversor**, no el del bridge, para evitar
desajustes de zona horaria); si ninguna lo está, la **próxima en empezar**.

**4.2 Tiempo restante.** Franja activa: `fin − ahora`. Franja futura: duración
completa. (Mínimo 1 min para evitar divisiones por cero.)

**4.3 SoC de partida.** Siempre el `BATTERY_SOC` **del momento de la
consulta**, tanto si la franja está activa como si no. Si la franja aún no ha
empezado se añade un aviso en `warnings`: el SoC real al inicio será menor
(la batería sigue descargándose hasta entonces), así que la sugerencia se
queda corta; cuanto más cerca del inicio se consulte (p. ej. 23:00 o,
mejor, 00:00–00:10), más exacta es. El tiempo usado es la duración completa
de la franja.

**4.4 Fórmulas.**

```
faltante_%   = TOU_SOC[i] − SoC_partida
Ah_necesarios = faltante_% / 100 × BATTERY_CAPACITY_AH / (BATTERY_CHARGE_EFFICIENCY_PCT/100)
I_mínima     = Ah_necesarios / horas_restantes
sugerida     = max(5, ceil(I_mínima × 1.25))      # margen de seguridad 25 %
sugerida     = min(sugerida, BATTERY_MAX_CHARGE_A)
```

Ejemplo (el caso real): SoC 25 %, objetivo 80 %, 314 Ah, eficiencia 99 %,
8 h → 174,4 Ah → 21,8 A mínimo → **28 A sugeridos**. Con los 18 A de fábrica
se estimaría ~70 % al final de la franja, consistente con lo observado.

**4.5 Avisos (`warnings`).** Corriente requerida > `BATTERY_MAX_CHARGE_A`
(status `infeasible`); potencia de carga estimada (`sugerida × V_batería`) >
`TOU_POWER` de la franja; franja no iniciada (el SoC al inicio será menor que el actual).

**4.6 Qué NO modela.** Aportación solar (de noche es 0; si la franja es
diurna la sugerencia es conservadora), consumo de la casa (la corriente de
carga es del lado batería; el consumo lo cubre la red aparte, solo se informa
`house_load_power_w`) y la reducción de corriente que el BMS aplica cerca del
tope de SoC. El margen del 25 % cubre esto último; si aun así no se alcanza el
objetivo, subir `SUGGESTION_SAFETY_MARGIN` en `deye.py`.

## 5. Uso recomendado desde Pulso

1. A inicio de franja: `POST {}` → leer `SUGGESTED_GRID_CHARGE_A` y `suggestion.status`.
2. Si `status=="ok"` y `applied_meets_suggested==false`: `POST {"GRID_CHARGE_A": <sugerido>}`.
3. Si `status=="infeasible"`: avisar al usuario (no se llegará al objetivo; subir
   el límite en el BMS/inversor o rebajar el SoC objetivo).
4. No llamar en bucle: cada escritura distinta persiste en flash del inversor
   (ver `CONTRACT_DEYE_TOU_WRITE.md` §5). Una vez por franja, y otra de
   comprobación a mitad, es suficiente.
