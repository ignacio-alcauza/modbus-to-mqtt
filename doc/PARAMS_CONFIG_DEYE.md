# Parámetros de configuración del inversor Deye — contrato para el consumidor

**Estado: implementado en `src/devices/deye.py` (2026-10-05).** Todo lo
descrito en la sección 1 ya está en el JSON de estado (`deye_inverter/state`,
MQTT) y en el webhook hacia Pulso, con `discovery: False` — no genera
entidades nuevas en Home Assistant.

**Este documento es solo de lectura.** Para que el consumidor *escriba* el
bloque TOU (`TOU_TIME`/`TOU_POWER`/`TOU_VOLTAGE`/`TOU_SOC`/`TOU_GRID_CHARGE`)
ver `doc/CONTRACT_DEYE_TOU_WRITE.md` — mismos campos, mismo encoding, vía
`POST /deye_inverter/tou`.

---

## 1. Qué recibe el consumidor

Los 25 campos nuevos viajan dentro del mismo JSON plano que el resto de
campos del Deye (mismo topic, mismo webhook) — no hay envoltorio ni trama
separada. Ejemplo real, 2026-10-05:

```json
{
  "...": "...resto de campos existentes sin cambios (PV2_POWER, BATTERY_POWER, HOUSE_LOAD_POWER, PRIORITY_LOAD, USE_TIMER, etc.)...",

  "WORK_MODE": 2,
  "WORK_MODE_TEXT": "ZeroExportToCT",
  "ENERGY_PATTERN": 1,
  "ENERGY_PATTERN_TEXT": "LoadFirst",
  "SOLAR_SELL": 1,
  "MAX_SELL_POWER": 6000,

  "TOU_TIME": ["00:00", "08:00", "10:00", "14:00", "20:00", "22:00"],
  "TOU_POWER": [6000, 6000, 6000, 6000, 6000, 6000],
  "TOU_VOLTAGE": [49.0, 49.0, 49.0, 49.0, 49.0, 49.0],
  "TOU_SOC": [80, 30, 30, 30, 30, 30],
  "TOU_GRID_CHARGE": [true, false, false, false, false, false],

  "BATTERY_CAPACITY_AH": 314,
  "BATTERY_MAX_CHARGE_A": 120,
  "BATTERY_MAX_DISCHARGE_A": 135,
  "BATTERY_CONTROL_MODE": 1,
  "BATTERY_CONTROL_MODE_TEXT": "BySOC",
  "BATTERY_RESISTANCE_MOHM": 8,
  "BATTERY_CHARGE_EFFICIENCY_PCT": 99.0,
  "BATTERY_SHUTDOWN_SOC_PCT": 15,
  "BATTERY_RESTART_SOC_PCT": 35,
  "BATTERY_LOWBATT_SOC_PCT": 20,
  "BATTERY_SHUTDOWN_V": 46.0,
  "BATTERY_RESTART_V": 52.0,
  "BATTERY_LOWBATT_V": 47.5
}
```

### 1.1 Campo a campo

| Campo | Tipo | Valores posibles | Significado |
|---|---|---|---|
| `WORK_MODE` | entero | `0`, `1`, `2` | Modo de exportación a red. `2`=Zero Export to CT (único valor confirmado en este sistema — ver §A.3). |
| `WORK_MODE_TEXT` | string | `"SellingFirst"` \| `"ZeroExportToLoad"` \| `"ZeroExportToCT"` \| `"Unknown"` | Texto legible de `WORK_MODE`. |
| `ENERGY_PATTERN` | entero | `0`, `1` | `0`=prioridad batería, `1`=prioridad carga. Mismo registro Modbus que `PRIORITY_LOAD` (ya publicado antes) — dos nombres para el mismo dato. |
| `ENERGY_PATTERN_TEXT` | string | `"BatteryPriority"` \| `"LoadFirst"` \| `"Unknown"` | Texto legible de `ENERGY_PATTERN`. |
| `SOLAR_SELL` | entero | `0`, `1` | `1` = el excedente solar se vende a red. |
| `MAX_SELL_POWER` | entero | ≥ 0 | Potencia máxima de venta a red, en **W**. |
| `TOU_TIME` | array[6] de string | `"HH:MM"` cada una | Hora de inicio de cada una de las 6 franjas horarias configuradas (Time of Use). |
| `TOU_POWER` | array[6] de entero | ≥ 0, **W** | Potencia objetivo de venta a red por franja. |
| `TOU_VOLTAGE` | array[6] de float | **V** | Voltaje de batería asociado a cada franja (afecta a cuándo se activa la venta). |
| `TOU_SOC` | array[6] de entero | `0`-`100`, **%** | SOC objetivo/mínimo de batería por franja. |
| `TOU_GRID_CHARGE` | array[6] de booleano | `true`/`false` | Si esa franja tiene habilitada la carga de batería desde red. |
| `BATTERY_CAPACITY_AH` | entero | ≥ 0, **Ah** | Capacidad nominal de batería configurada en el inversor. |
| `BATTERY_MAX_CHARGE_A` | entero | `0`-`185`, **A** | Corriente máxima de carga de batería. |
| `BATTERY_MAX_DISCHARGE_A` | entero | `0`-`185`, **A** | Corriente máxima de descarga de batería. |
| `BATTERY_CONTROL_MODE` | entero | `0`, `1`, `2` | Cómo decide el inversor el estado de la batería: `0`=por voltaje, `1`=por SOC, `2`=sin batería. |
| `BATTERY_CONTROL_MODE_TEXT` | string | `"ByVoltage"` \| `"BySOC"` \| `"NoBattery"` \| `"Unknown"` | Texto legible de `BATTERY_CONTROL_MODE`. |
| `BATTERY_RESISTANCE_MOHM` | entero | ≥ 0, **mΩ** | Resistencia interna de batería configurada. |
| `BATTERY_CHARGE_EFFICIENCY_PCT` | float | `0`-`100`, **%** | Eficiencia de carga configurada. |
| `BATTERY_SHUTDOWN_SOC_PCT` | entero | `0`-`100`, **%** | SOC por debajo del cual el inversor corta (protección). |
| `BATTERY_RESTART_SOC_PCT` | entero | `0`-`100`, **%** | SOC de recuperación tras el corte por SOC. |
| `BATTERY_LOWBATT_SOC_PCT` | entero | `0`-`100`, **%** | SOC de aviso de batería baja. |
| `BATTERY_SHUTDOWN_V` | float | **V** | Voltaje por debajo del cual el inversor corta (protección). |
| `BATTERY_RESTART_V` | float | **V** | Voltaje de recuperación tras el corte por voltaje. |
| `BATTERY_LOWBATT_V` | float | **V** | Voltaje de aviso de batería baja. |

### 1.2 Notas de contrato

- **Los 5 arrays `TOU_*` se publican todos juntos o ninguno.** Si falla la
  lectura de cualquier registro del bloque horario, no aparece ninguno de
  los 5 ese ciclo — nunca hay un array con huecos o de longitud distinta
  de 6.
- **`TOU_GRID_CHARGE` ya viene decodificado a booleano** — el consumidor no
  necesita conocer el bitmask Modbus subyacente.
- **Los campos `*_TEXT` son siempre strings, nunca `null`** — si el valor
  crudo no coincide con ningún caso conocido, el texto es `"Unknown"`.
- **`PRIORITY_LOAD` y `USE_TIMER`** (publicados desde antes de este cambio)
  **no se han tocado** — mismo nombre, mismo significado. `ENERGY_PATTERN`
  lee el mismo registro que `PRIORITY_LOAD` pero con nombre más claro; son
  el mismo dato con dos etiquetas.
- **Como el resto de campos de configuración del productor, estos no tienen
  historial** — son el valor *actual* en cada ciclo de lectura, no un
  registro de cambios.
- Si todo el bloque de configuración del Deye falla al leerse ese ciclo,
  ninguno de estos 25 campos aparece en el payload (igual que el resto de
  campos del dispositivo en un fallo de lectura).

### 1.3 Nivel de confianza por campo (resumen)

La mayoría de estos campos vienen de documentación de terceros sin garantía
oficial para este sub-modelo exacto de inversor — el anexo (§A) tiene el
detalle completo de cómo se verificó cada uno. Resumen:

| Confianza | Campos | Cómo se verificó |
|---|---|---|
| **Máxima** (prueba activa en vivo) | `TOU_GRID_CHARGE` | Se cambió el valor real en el inversor y se comparó antes/después — ver §A.2 |
| **Máxima** (confirmado por el propietario) | `WORK_MODE`/`WORK_MODE_TEXT` (solo el valor `2`, que es el permanente de este sistema) | El propietario confirmó que el sistema está en "Zero Export to CT" — ver §A.3 |
| **Alta** (coincide con Deye Cloud o con el JK BMS) | `ENERGY_PATTERN`, `SOLAR_SELL`, `MAX_SELL_POWER`, `TOU_TIME`, `TOU_POWER`, `TOU_SOC`, `BATTERY_CAPACITY_AH` | Valor cruzado contra el export de Deye Cloud o, en el caso de la capacidad, contra el propio JK BMS — ver §A.1 y §A.4 |
| **Media** (documentado pero sin cruce externo) | `TOU_VOLTAGE`, el resto de campos `BATTERY_*` | Identificados por el documento Modbus oficial monofásico, valores plausibles, pero Deye Cloud no exportó un valor con el que contrastarlos — ver §A.4 |
| **Teórico, sin verificar** | `WORK_MODE`/`WORK_MODE_TEXT` para los valores `0` y `1` (nunca se van a probar) | Inferido del documento oficial, nunca confirmado en vivo — ver §A.3 |

---

## Anexo A — investigación y verificación completa

Detalle de cómo se llegó a cada dirección y cada decodificación. Útil para
auditar el contrato de la sección 1 o para retomar la investigación de lo
pendiente (§A.6).

### A.0 Fuentes y aviso

**Fuentes:**
1. Export de Deye Cloud, `doc/batch-config-2510112106-20261005122558.xls`
   (HTML real, no XLS binario), 2026-10-05 12:25:58 UTC+02:00, Device SN
   `2510112106` (coincide con `DEVICE_SERIAL` del productor).
2. Documento Modbus RTU bilingüe (chino/inglés) para inversores híbridos
   monofásicos Deye/Sunsynk, obtenido de
   [githubDante/deye-controller](https://github.com/githubDante/deye-controller)
   (`docs/sunsynk_modbus_deye_single_phase.docx`), un proyecto Python
   activamente mantenido con soporte probado para la familia de inversores
   híbridos Deye.
3. Lecturas en vivo contra el hardware real, 2026-10-05.

**Aviso:** la documentación Modbus genérica de Deye **no es fiable sin
verificación empírica** para este sub-modelo (SUN-6K-SG05LP1-EU-AM2-P) — se
detectaron dos conflictos directos:
- El registro `108` se documenta como "Maximum battery charge current" en una
  fuente comunitaria para SG01LP1/SG02LP1/SG03LP1, pero en este inversor es
  `PV_DAILY_PRODUCTION` (ya verificado y en producción).
- El registro `142` se documenta como "System Work Mode" (enum 0/1/2) en una
  librería Python para inversores trifásicos SG04LP3/SG05LP3, pero en este
  inversor monofásico el registro `142` lee `314` — no es Work Mode aquí
  (ver §A.3).

### A.1 Bloque Time of Use (TOU) — direcciones 243-273

| Addr | Campo | Valor en vivo | Deye Cloud / doc oficial | Estado |
|---|---|---|---|---|
| 243 | Energy management mode (`0`=Battery priority, `1`=Load first) | 1 | "Energy Pattern: Load First" | ✓ Confirmado (doc oficial + Deye Cloud) |
| 244 | Limit control function / mecanismo de Work Mode (`0`=sell enabled, `1`=built-in, `2`=external/CT) — ver §A.3 | 2 | "System Work Mode: Zero Export to CT" | ✓✓ Confirmado por el propietario del sistema |
| 245 | Max Sell Power (W) | 6000 | "Max Sell Power: 6000W" | ✓ Confirmado (doc oficial + Deye Cloud exacto) |
| 246 | External current sensor clamp phase (orientación física del CT) | 0 | — (no está en el export de Deye Cloud) | Identificado por doc oficial, no publicado (no es útil para el consumidor) |
| 247 | Solar sell (`0`=no vende, `1`=vende excedente) | 1 | "Solar Sell: Enable" | ✓ Confirmado (doc oficial + Deye Cloud exacto) |
| 248 | `USE_TIMER` / Time of Use ON-OFF (ya en el productor) | 255 | "Time of Use: ON" (`0`=Disable, `0xFF`=enabled) | ✓ Ya confirmado antes, doc oficial lo corrobora |
| 249 | Reservado/sin usar (doc oficial: "预留 undefined") | 0 | — | Confirmado como reservado, no publicado |
| 250–255 | Sell mode time point 1–6 (HHMM) | 0000/0800/1000/1400/2000/2200 | Selling Mode Time 1-6 | ✓ Confirmado exacto |
| 256–261 | Sell mode time point 1–6 power (W) | 6000 ×6 | Time1-6 GPS: 6000W ×6 | ✓ Confirmado exacto |
| 262–267 | Sell mode time point 1–6 voltage (×0.01V) | 4900 ×6 → 49.00V | — (no está en el export de Deye Cloud) | Identificado por doc oficial, sin cruce externo |
| 268–273 | Capacity 1–6 (SOC objetivo por franja, %) | 80/30/30/30/30/30 | Time 1-6 SOC1: 80%/30%×5 | ✓ Confirmado exacto |

**Corrección histórica:** en una versión anterior de esta investigación se
había propuesto que los registros `246`/`247` eran los bitmask "Time N Gen"/
"Time N Grid Charge", basándose solo en coincidencia casual de valores (`0`
y `1`). El documento oficial los identifica como algo distinto (orientación
del CT clamp y Solar Sell). Las flags reales de "Grid Charge" por franja
están en 274-279 — ver §A.2.

### A.2 "Time N Grid Charge" — resuelto por prueba activa (2026-10-05)

El documento oficial sitúa "Time point N charge enable" en los registros
**274–279** con rango `[0,1]`, pero la lectura en vivo inicial daba
`[5, 4, 4, 4, 4, 4]` — no encajaba con ese rango como valor booleano plano.

**Prueba activa realizada:** con "Time 2 Grid Charge" en OFF, snapshot
inicial = `[5, 4, 4, 4, 4, 4]` (addr 274-279). El propietario activó "Time 2
Grid Charge" desde la app (franja 08:00-10:00, 6000W, 30% SOC — configuración
ya conocida, solo se cambió el enable). Nueva lectura = `[5, 5, 4, 4, 4, 4]`
— **solo `275` (Time 2) cambió**, de `4` a `5`. Después se revirtió el
cambio en la app y se confirmó que `275` volvió a `4`.

**Decodificación confirmada:** no es un booleano plano `[0,1]` como decía el
documento — es un **bitmask de 3 bits por franja**, donde el **bit 0** es el
enable de Grid Charge (publicado como `TOU_GRID_CHARGE`):

| Valor | Binario | Grid Charge |
|---|---|---|
| `4` | `0b100` | OFF |
| `5` | `0b101` | **ON** |

El bit 1 (`0b10`=2) se mantiene constante en las 6 franjas y no participa en
este cambio — probablemente codifica "Gen" (que Deye Cloud muestra OFF en
las 6 franjas, consistente con estar siempre en el mismo valor), **sin
confirmar todavía** cuál bit exacto le corresponde ni con qué valor — ver
§A.6.

| Addr | Franja | Valor antes | Valor después | Grid Charge (Deye Cloud) |
|---|---|---|---|---|
| 274 | Time 1 | 5 | 5 (sin cambio) | ON (ya estaba ON) |
| 275 | Time 2 | 4 | **5** | OFF → **ON** (cambio confirmado) |
| 276 | Time 3 | 4 | 4 | OFF |
| 277 | Time 4 | 4 | 4 | OFF |
| 278 | Time 5 | 4 | 4 | OFF |
| 279 | Time 6 | 4 | 4 | OFF |

✓✓ Confirmado por prueba activa (antes/después en vivo, no solo correlación
de valores) — el nivel de evidencia más fuerte de todo este documento,
equivalente al usado para el modo flotante del JK BMS.

### A.3 "System Work Mode" — resuelto, pero no es un único registro

Deye Cloud muestra `System Work Mode: Zero Export to CT` como una etiqueta
única, pero **este inversor monofásico no tiene un registro Work Mode
enum 0/1/2 como los modelos trifásicos** (que sí usan el registro `142`,
confirmado por una librería Python de terceros — ver aviso en §A.0). En su
lugar, el comportamiento se controla mediante el registro `244` ("limit
control function"), con la siguiente semántica, confirmada por el documento
oficial monofásico:

| Valor `244` | Significado (doc oficial) | Equivalente conceptual al "Work Mode" trifásico |
|---|---|---|
| `0` | "sell electricity enabled" | ≈ Selling First — sin verificar, teórico |
| `1` | "built-in enabled" (medición interna del propio inversor) | ≈ Zero Export to Load — sin verificar, teórico |
| `2` | "external enabled" (sensor CT externo) | ≈ **Zero Export to CT** — ✓✓ confirmado por el propietario del sistema |

Valor real leído: `244 = 2` → "external enabled" → coincide exactamente con
"Zero Export to CT" de Deye Cloud (CT = Current Transformer = el sensor
externo). **Confirmado por el propietario (2026-10-05):** el sistema está
configurado en "Zero Export to CT" y ese valor **nunca se va a cambiar** (no
se hará la prueba activa de alternar el modo para verificar `0`/`1`). La
correspondencia `244=2 ↔ Zero Export to CT` queda confirmada con alta
confianza para el estado real y permanente de este sistema; los valores `0`
y `1` del enum siguen siendo una inferencia teórica sin contrastar, sin
previsión de llegar a verificarse.

### A.4 Batería — Battery Setting 1/2/3 (confirmado)

| Addr | Campo | Valor en vivo | Rango | Notas |
|---|---|---|---|---|
| 204 | Battery Capacity (Ah) | 314 | 0~2000 | ✓✓ Coincide EXACTO con `CAP_BAT_CELL` del JK BMS (314000 mAh = 314 Ah) — validación cruzada entre dos sistemas independientes |
| 210 | Max A Charge (A) | 120 | 0~185 (Deye Cloud limita a 0~135 en su UI) | ✓ Confirmado, nombre idéntico al de Deye Cloud |
| 211 | Max A Discharge (A) | 135 | 0~185 (Deye Cloud limita a 0~135) | ✓ Confirmado — el valor coincide exactamente con el tope que permite la UI de Deye Cloud |
| 213 | Modo de control de batería (`0`=por voltaje, `1`=por capacidad/SOC, `2`=sin batería) | 1 | — | ✓ Confirmado — `1`=SOC, coherente con tener un BMS inteligente reportando SOC directo |
| 215 | Resistencia interna de batería (mΩ) | 8 | 0~6000 | ✓ Confirmado — valor plausible |
| 216 | Eficiencia de carga de batería (×0.1%) | 990 → 99.0% | 0~100 | ✓ Confirmado — corresponde a "Batt Charge Efficiency" de Deye Cloud, valor plausible |
| 217 | Battery capacity ShutDown (% corte por bajo SOC) | 15 | 0~100 | ✓ Confirmado |
| 218 | Battery capacity Restart (% recuperación) | 35 | 0~100 | ✓ Confirmado |
| 219 | Battery capacity LowBatt (% aviso batería baja) | 20 | 0~100 | ✓ Confirmado |
| 220 | Battery voltage ShutDown (×0.01V) | 4600 → 46.00V | 3800~6100 | ✓ Confirmado — coherente con las protecciones del BMS (VOL_SYS_PWR_OFF=44.8V, VOL_CELL_UV×16=45.6V) |
| 221 | Battery voltage Restart (×0.01V) | 5200 → 52.00V | 3800~6100 | ✓ Confirmado — doc da ejemplo "52V", coincide exacto con el valor real |
| 222 | Battery voltage LowBatt (×0.01V) | 4750 → 47.50V | 3800~6100 | ✓ Confirmado |

### A.5 Generador / carga desde red (Battery Setting-3) — identificado, no publicado

Estos registros se identificaron durante la investigación pero **no se
publican** (sin generador conectado en esta instalación, bajo interés para
Pulso):

| Addr | Campo | Valor en vivo | Notas |
|---|---|---|---|
| 223 | Tiempo máximo de operación del generador (×0.1 h) | 240 → 24.0 h | Sin generador conectado |
| 224 | Tiempo de enfriamiento del generador (×0.1 h) | 1440 → 144.0 h | ídem |
| 225 | Voltaje de arranque de carga por generador (×0.01V) | 4900 → 49.00V | ídem |
| 226 | SOC de arranque de carga por generador (%) | 30 | ídem |
| 227 | Corriente de carga del generador (A) | 40 | ídem |
| 228 | Voltaje de arranque de carga desde red (×0.01V) | 4900 → 49.00V | — |
| 229 | SOC de arranque de carga desde red (%) | 10 | — |
| 230 | Corriente de carga desde red (A) | 18 | — |
| 231 | Gen Charge enable (`0`/`1`) | 0 | Deshabilitado |
| 232 | Grid Charge enable (`0`/`1`) — switch maestro, distinto de los flags por franja de §A.2 | 1 | ✓ Habilitado, coherente con "Time1 Grid Charge: ON" |
| 233 | Solar Input as PSU (`0`=solar, `1`=PSU) | 0 | Modo normal |
| 234 | Gen Force (forzar generador como carga) | 0 | Deshabilitado |
| 235 | Generador como salida de carga (`0`=deshabilitado, `1`=SmartLoad, `2`=entrada inversor) | 0 | Deshabilitado |
| 236 | SmartLoad OFF — voltaje batería (×0.01V) | 5100 → 51.00V | — |
| 237 | SmartLoad OFF — SOC batería (%) | 95 | — |
| 238 | SmartLoad ON — voltaje batería (×0.01V) | 5400 → 54.00V | — |
| 239 | SmartLoad ON — SOC batería (%) | 100 | — |
| 240 | PWM Test Enable | 0 | Valor por defecto |

### A.6 Pendiente (no bloqueante)

El bit 1 del registro bitmask 274-279 (posiblemente "Time N Gen") no se ha
confirmado — solo se verificó el bit 0 (Grid Charge) por prueba activa. No
se publica nada derivado de ese bit por ahora. Si llega a interesar, la
misma técnica de §A.2 (cambiar un valor conocido en la app, comparar
antes/después) lo resolvería.
