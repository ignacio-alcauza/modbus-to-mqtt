# Parámetros de configuración del JK BMS — contrato para el consumidor

Campos de **configuración** (no telemetría en tiempo real) que el productor
publica en la trama del BMS, tanto en `jkbms/state` (MQTT) como en el payload
webhook hacia Pulso. Mismo JSON plano para ambos destinos.

**Fuente:** `src/devices/jkbmsv2.py` (`CONFIG_REGISTERS`, `read_config_block()`,
`get_all_data()`). Desde 2026-10-05 se publica el bloque de configuración
**completo** (antes solo se pasaba un subconjunto de 5 campos + flags).

---

## 1. Switches (enteros `0`/`1`, no booleanos JSON)

| Campo | Valores | Significado |
|---|---|---|
| `BAT_CHARGE_EN` | `0` / `1` | Switch de carga. `1` = carga habilitada. |
| `BAT_DISCHARGE_EN` | `0` / `1` | Switch de descarga. `1` = descarga habilitada. |
| `BALAN_EN` | `0` / `1` | Switch de balanceo activo entre celdas. `1` = habilitado. |

## 2. Identificación / dirección

| Campo | Unidad | Valor típico | Significado |
|---|---|---|---|
| `DEV_ADDR` | — | `1` | Modbus Unit ID configurado en el propio BMS — debería coincidir con `modbus_unit` en `config.yml`. Si no coincide, hay un BMS mal configurado o una dirección duplicada en el bus. |
| `CELL_COUNT` | — | `16` | Número de celdas configurado en el BMS. Compárese con `len(CELL_VOLTAGES)` del bloque realtime — si difieren, hay una celda física desconectada/mal detectada. |
| `CAP_BAT_CELL` | mAh | `314000` | Capacidad nominal configurada de la batería (314 Ah). |

## 3. Protecciones de voltaje (todas en **mV**, por celda salvo que se indique)

| Campo | Valor típico | Significado |
|---|---|---|
| `VOL_CELL_UV` | 2850 | Protección por subvoltaje de celda — por debajo de esto el BMS corta descarga. |
| `VOL_CELL_UVPR` | 3100 | Voltaje de recuperación tras subvoltaje (histéresis de rearme). |
| `VOL_CELL_OV` | 3600 | Protección por sobrevoltaje de celda — por encima de esto el BMS corta carga. |
| `VOL_CELL_OVPR` | 3400 | Voltaje de recuperación tras sobrevoltaje. |
| `VOL_BALAN_TRIG` | 5 | Diferencia de voltaje entre celdas que dispara el balanceo. |
| `VOL_START_BALAN` | 3420 | Voltaje de celda al que arranca el balanceo. |
| `VOL_SOC_100` | 3450 | Voltaje de celda que el BMS interpreta como SOC=100%. |
| `VOL_SOC_0` | 3000 | Voltaje de celda que el BMS interpreta como SOC=0%. |
| `VOL_CELL_RCV` | 3460 | Voltaje de carga recomendado (absorción). |
| `VOL_CELL_RFV` | 3380 | Voltaje de carga flotante (setpoint — distinto del switch `Modo flotante` de §6, que indica si el modo está *activo*, no el voltaje objetivo). |
| `VOL_SYS_PWR_OFF` | 2800 | Voltaje de apagado automático del sistema. |
| `VOL_SMART_SLEEP` | 3375 | Voltaje de entrada a modo sleep. |

## 4. Protecciones de corriente (mA)

| Campo | Valor típico | Significado |
|---|---|---|
| `CUR_BAT_COC` | 150000 | Corriente máxima de carga continua (150 A). |
| `CUR_BAT_DOC` | 150000 | Corriente máxima de descarga continua (150 A). |
| `CUR_BALAN_MAX` | 2000 | Corriente máxima de balanceo (2 A). |

## 5. Protecciones de temperatura (°C, ya escaladas — no ×0.1 crudo)

| Campo | Valor típico | Significado |
|---|---|---|
| `TMP_BAT_COT` | 55.0 | Protección por sobretemperatura en carga. |
| `TMP_BAT_COTPR` | 50.0 | Recuperación tras sobretemperatura en carga. |
| `TMP_BAT_DOT` | 60.0 | Protección por sobretemperatura en descarga. |
| `TMP_BAT_DOTPR` | 50.0 | Recuperación tras sobretemperatura en descarga. |
| `TMP_BAT_CUT` | 1.0 | Protección por baja temperatura en carga. |
| `TMP_BAT_CUTPR` | 2.0 | Recuperación tras baja temperatura en carga. |
| `TMP_MOS_OT` | 80.0 | Protección por sobretemperatura del MOS. |
| `TMP_MOS_OTPR` | 70.0 | Recuperación tras sobretemperatura del MOS. |

## 6. Tiempos / retardos (segundos salvo que se indique)

| Campo | Valor típico | Significado |
|---|---|---|
| `TIM_BAT_COC_DLY` | 3 | Retardo antes de disparar protección por sobrecorriente de carga. |
| `TIM_BAT_COC_PR_DLY` | 60 | Retardo de recuperación tras sobrecorriente de carga. |
| `TIM_BAT_DOC_DLY` | 300 | Retardo antes de disparar protección por sobrecorriente de descarga. |
| `TIM_BAT_DOC_PR_DLY` | 60 | Retardo de recuperación tras sobrecorriente de descarga. |
| `TIM_BAT_SCP_PR_DLY` | 15 | Retardo de recuperación tras cortocircuito. |
| `TIM_PRODISCHARGE` | 5 | Tiempo de pre-descarga. |
| `TIM_SMART_SLEEP` | 6144 | Tiempo de smart sleep — **decodificación sin confirmar del todo** (ver nota ⁴ abajo); no usar como fuente fiable todavía. |
| `SCP_DELAY` | 30 (µs, no segundos) | Retardo de protección por cortocircuito. |

## 7. `CONFIG_FLAGS` — bitmask crudo y decodificado

| Campo | Tipo | Significado |
|---|---|---|
| `CONFIG_FLAGS` | entero | Valor crudo del bitmask (16 bits, 10 usados). Útil solo para depuración de bajo nivel; para el consumidor normal usar `CONFIG_FLAGS_DECODED`. |
| `CONFIG_FLAGS_DECODED` | objeto | 10 interruptores de configuración avanzada, cada uno `true`/`false`. Ver tabla completa abajo. |

### 7.1 Las 10 claves de `CONFIG_FLAGS_DECODED`

| Clave (string exacto) | Bit | Significado | Visible en app BMS como |
|---|---|---|---|
| `Calefacción` | 0 | Switch de calefacción de celdas | Heating |
| `Deshabilitar sensor temp` | 1 | Sensor de temperatura deshabilitado | Disable Temp. Sensor |
| `GPS Heartbeat` | 2 | Detección de latido GPS | — |
| `Puerto RS485/CAN` | 3 | `true` = puerto en modo RS485, `false` = modo CAN (selector, no on/off de función) | — |
| `LCD siempre encendido` | 4 | Pantalla del BMS siempre encendida | Display Always On |
| `Cargador dedicado` | 5 | Identificación de cargador dedicado | — |
| `Smart Sleep` | 6 | Modo de bajo consumo activado | Smart Sleep On |
| `Deshab. limitación paralelo` | 7 | Limitador de corriente en paralelo deshabilitado | Disable Par-Limiter |
| `Almacenamiento periódico` | 8 | Guardado periódico de datos en el BMS | Timed Stored Data |
| `Modo flotante` | 9 | **Carga en modo flotación activa** | **Charging Float Mode** |

### Ejemplo real verificado en producción (2026-10-05)

```json
{
  "DEV_ADDR": 1,
  "CELL_COUNT": 16,
  "CAP_BAT_CELL": 314000,
  "VOL_CELL_UV": 2850,
  "VOL_CELL_OV": 3600,
  "VOL_CELL_RCV": 3460,
  "VOL_CELL_RFV": 3380,
  "VOL_START_BALAN": 3420,
  "CUR_BAT_COC": 150000,
  "CUR_BAT_DOC": 150000,
  "TMP_BAT_COT": 55.0,
  "TMP_MOS_OT": 80.0,
  "CONFIG_FLAGS": 4608,
  "CONFIG_FLAGS_DECODED": {
    "Calefacción": false,
    "Deshabilitar sensor temp": false,
    "GPS Heartbeat": false,
    "Puerto RS485/CAN": false,
    "LCD siempre encendido": false,
    "Cargador dedicado": false,
    "Smart Sleep": false,
    "Deshab. limitación paralelo": false,
    "Almacenamiento periódico": false,
    "Modo flotante": true
  }
}
```

Verificado cruzando contra la app Bluetooth del BMS (captura de pantalla de la pestaña "Control"): `DEV_ADDR=1` coincide con el Unit ID real, y los 10 flags coinciden campo a campo (solo "Modo flotante" activo).

## 8. Resistencias de cableado por celda (diagnóstico, no mostrar en dashboard normal)

| Campo | Tipo | Significado |
|---|---|---|
| `CELL_CON_WIRE_RES` | array de 32 enteros, µΩ | Resistencia del cable de conexión de cada celda (0–31; esta instalación usa 16, el resto quedan a 0 o sin sentido). Las dos últimas posiciones (30, 31) pueden tener una dirección Modbus sin verificar del todo — tratar con cautela si aparecen valores raros ahí. |

---

## Notas de contrato para el consumidor

- **Ningún campo de esta sección genera entidades nuevas en Home Assistant** — el discovery de HA es una lista estática independiente del payload (`get_discovery_sensors()`), así que esta ampliación es puramente aditiva al JSON y no afecta a HA.
- **El bloque de configuración entero puede faltar** del payload si `read_config_block()` falla por completo (p.ej. fallo de conexión Modbus durante ese ciclo) — en ese caso ninguno de los campos de este documento está presente, no solo algunos.
- `CONFIG_FLAGS_DECODED` específicamente puede faltar incluso si el resto del bloque de configuración llega bien, porque se lee en peticiones Modbus separadas del resto (ver `TECHNICAL.md` §2.3.1). El consumidor debe tratar su ausencia como "dato no disponible este ciclo", no como "todos los flags en false".
- No hay versión numérica/histórica de estos parámetros: son el valor *actual* leído en cada ciclo, no un registro de cambios. Si Pulso necesita detectar cambios de configuración, debe comparar contra el valor anterior que ya tenga almacenado.
- Los campos de temperatura (`TMP_*`) ya vienen escalados a °C (no hace falta dividir por 10 en el consumidor).
- `TIM_SMART_SLEEP` (nota ⁴): el valor crudo decodificado (6144) no parece coherente como horas directas con Smart Sleep OFF; es posible que requiera partirse en byte alto/bajo. No se ha investigado a fondo por ser un campo de baja prioridad — tratarlo como informativo, no fiable al 100%, hasta nueva verificación.

---

## Referencia completa

Ver `TECHNICAL.md` §2.3 (mapa de registros) y §2.3.1 (historial de la corrección de direccionamiento de `DEV_ADDR`/`CONFIG_FLAGS`/etc.) y §5.2 (formato completo de la trama de estado, incluidos `_schema_version` y `_observed_at`).
