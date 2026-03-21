# modbus-to-mqtt — Documentación Técnica

**Última actualización:** 2026-03-21
**Hardware:** JK-PB2A16S20P (HW v19, FW v27) + Deye SUN-6K-SG05LP1-EU-AM2-P

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [JK BMS — Mapa Modbus](#2-jk-bms--mapa-modbus)
3. [JK BMS — Estrategia de lectura por páginas](#3-jk-bms--estrategia-de-lectura-por-páginas)
4. [Deye Inversor — Mapa Modbus](#4-deye-inversor--mapa-modbus)
5. [Publicación MQTT / Home Assistant Discovery](#5-publicación-mqtt--home-assistant-discovery)
6. [Configuración](#6-configuración)

---

## 1. Arquitectura general

```
┌─────────────────┐        Modbus TCP        ┌────────────────────────┐
│  JK BMS         │ ◄──────────────────────► │                        │
│  192.168.1.136  │        port 502          │   modbus-to-mqtt       │
│  unit_id: 1     │                          │   (src/main.py)        │
└─────────────────┘                          │                        │
                                             │  Ciclo JK BMS: 30s     │
┌─────────────────┐        Modbus TCP        │  Ciclo Deye:   10s     │
│  Deye Inversor  │ ◄──────────────────────► │                        │
│  192.168.1.133  │        port 502          └──────────┬─────────────┘
│  unit_id: 1     │                                     │ MQTT
└─────────────────┘                                     ▼
                                             ┌────────────────────────┐
                                             │  Broker MQTT           │
                                             │  (Home Assistant)      │
                                             └────────────────────────┘
```

**Ficheros clave:**

| Fichero | Función |
|---|---|
| `src/main.py` | Loop principal, inicialización, publicación |
| `src/devices/jkbmsv2.py` | Driver JK BMS (mapa + lectura + decodificación) |
| `src/devices/deye.py` | Driver Deye Inversor (mapa + lectura + decodificación) |
| `src/mqtt/publisher.py` | Cliente MQTT, discovery HA, availability |
| `src/utils/modbus.py` | Wrapper Modbus TCP con reintentos |
| `config.yml` | Configuración de dispositivos y broker |

---

## 2. JK BMS — Mapa Modbus

**Modelo:** JK-PB2A16S20P · HW v19 · FW v27
**Protocolo Modbus:** función 0x03 (read holding registers)
**Nota:** Las direcciones del documento oficial V1.1 **no** coinciden con el firmware v27. Las direcciones documentadas aquí son el resultado de sondeo empírico verificado contra valores reales del dispositivo.

### 2.1 Bloque 0x1400 — Información del dispositivo

Lectura: una sola petición desde `0x1400` con `count=72` (obligatorio, ver sección 3).

| Campo | Addr | Tipo | Unidad | Descripción |
|---|---|---|---|---|
| MANUFACTURER_ID | 0x1400 | ASCII(16) | — | Modelo: `JK-PB2A16S20P` |
| HW_VERSION | 0x1408 | ASCII(8) | — | Versión hardware: `19A` |
| SW_VERSION | 0x140C | ASCII(8) | — | Versión firmware: `19.27` |
| ODD_RUN_TIME | 0x1410 | UINT32 | s | **Uptime acumulado** (fuente correcta de uptime) |
| PWR_ON_TIMES | 0x1412 | UINT32 | — | Número de encendidos |
| BLE_NAME | 0x1414 | ASCII(16) | — | Nombre Bluetooth |
| BLE_PIN | 0x141C | ASCII(16) | — | PIN Bluetooth |
| FIRST_ON_DATE | 0x1424 | ASCII(8) | — | Fecha primer encendido |
| SERIAL_NO | 0x1428 | ASCII(16) | — | Número de serie |
| USER_PRIVATE_DATA | 0x1430 | ASCII(16) | — | Datos usuario |
| PASSWORD | 0x1438 | ASCII(16) | — | Contraseña BMS |

### 2.2 Bloque 0x1200 — Datos en tiempo real

Lectura: múltiples peticiones por rangos + overrides dedicados (ver sección 3).

#### Voltajes de celdas

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| CELL_VOLTAGES[0..15] | 0x1200–0x120F | UINT16 ×16 | ×0.001 V | Voltaje individual de cada celda |

#### Estadísticas de celdas

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| CELL_STA | 0x1240 | UINT32 | bitmask | BIT[n]=1 → celda n presente; valor típico `0x0000FFFF` (16 celdas) |
| CELL_VOL_AVE | 0x1242 | UINT16 | ×0.001 V | Voltaje promedio |
| CELL_VDIF_MAX | 0x1243 | UINT16 | ×0.001 V | Diferencia máxima entre celdas |
| MAX_VOL_CELL_NBR | 0x1244 | UINT8_HIGH | — | Índice celda con mayor voltaje |
| MIN_VOL_CELL_NBR | 0x1244 | UINT8_LOW | — | Índice celda con menor voltaje |

#### Resistencias de celdas

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| CELL_RESISTANCES[0..15] | 0x124A–0x1259 | UINT16 ×16 | ×0.001 mΩ | Resistencia interna por celda |

> Requiere lectura dedicada desde página `0x124A` (ver sección 3.2).

#### Temperaturas

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| TEMP_MOS | 0x1285 | INT16 | ×0.1 °C | Temperatura placa MOS |
| TEMP_BAT1 | 0x1292 | INT16 | ×0.1 °C | Sensor temperatura 1 |
| TEMP_BAT2 | 0x1293 | INT16 | ×0.1 °C | Sensor temperatura 2 |
| TEMP_BAT4 | 0x12ED | INT16 | ×0.1 °C | Sensor temperatura 4 |
| TEMP_BAT5 | 0x12EE | INT16 | ×0.1 °C | Sensor temperatura 5 |

> TEMP_BAT1/2 requieren página `0x1288`. TEMP_BAT4/5 requieren página `0x12E0`. TEMP_BAT3 no conectado en este hardware.

#### Pack — Voltaje / Corriente

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| BAT_VOL | 0x1289 | UINT16 | ×0.001 V | Voltaje total del pack |
| BAT_CURRENT | 0x128C | INT32 | ×0.001 A | Corriente (+carga, −descarga) |
| BALAN_CURRENT | 0x1286 | INT16 | ×0.001 A | Corriente de balanceo activo |

#### SOC / Capacidad / Ciclos

| Campo | Addr | Tipo | Escala | Descripción |
|---|---|---|---|---|
| SOC | 0x12A3 | UINT8_LOW | % | Estado de carga |
| BALAN_STA | 0x12A3 | UINT8_HIGH | — | Estado balanceo (0=Off, 1=Carga, 2=Desc.) |
| SOC_CAP_REMAIN | 0x12A4 | UINT32 | ×0.001 Ah | Capacidad restante |
| SOC_FULL_CHARGE_CAP | 0x12A6 | UINT32 | ×0.001 Ah | Capacidad carga completa actual |
| SOC_CYCLE_COUNT | 0x12B6 | UINT16 | — | Número de ciclos completos |
| SOC_CYCLE_CAP | 0x12B7 | UINT16 | ×0.1 Ah | Capacidad acumulada total en ciclos |

> Estos registros requieren lectura desde página `0x12A0`/`0x12B0` para ser correctos.

#### Estado y alarmas

| Campo | Addr | Tipo | Descripción |
|---|---|---|---|
| CHARGE_STA | 0x12B8 | UINT8_LOW | Carga habilitada (1=ON) |
| DISCHARGE_STA | 0x12B8 | UINT8_HIGH | Descarga habilitada (1=ON) |
| ALARMS | 0x12A1 | UINT32 | Bitmask 22 bits de alarmas activas |
| RUNTIME | 0x129E | UINT32 | Contador sesión (NO es el uptime del sistema) |

> **Uptime correcto:** usar `ODD_RUN_TIME` del bloque 0x1400, no `RUNTIME`.

#### Alarmas — Bits

| Bit | Descripción | Bit | Descripción |
|---|---|---|---|
| 0 | Resistencia cable alta | 11 | Subvoltaje celda |
| 1 | MOS sobre-temperatura | 12 | Subvoltaje pack |
| 2 | Nº celdas incorrecto | 13 | Sobrecorriente descarga |
| 3 | Error sensor corriente | 14 | Cortocircuito descarga |
| 4 | Sobrevoltaje celda | 15 | Sobre-temperatura descarga |
| 5 | Sobrevoltaje pack | 16 | Error MOS carga |
| 6 | Sobrecorriente carga | 17 | Error MOS descarga |
| 7 | Cortocircuito carga | 18 | GPS desconectado |
| 8 | Sobre-temperatura carga | 19 | Cambiar contraseña |
| 9 | Baja-temperatura carga | 20 | Fallo inicio descarga |
| 10 | Error comunicación interna | 21 | Alarma sobre-temp batería |

### 2.3 Bloque 0x1000 — Configuración (R/W)

Lectura: una sola petición `chunk_size=68` desde `0x1000` + override desde `0x1084` (ver sección 3).

#### Protecciones de voltaje (UINT32, unidad mV)

| Campo | Addr | Valor típico | Descripción |
|---|---|---|---|
| VOL_SMART_SLEEP | 0x1000 | 3375 mV | Voltaje entrada modo sleep |
| VOL_CELL_UV | 0x1002 | 2850 mV | Protección subvoltaje celda |
| VOL_CELL_UVPR | 0x1004 | 3100 mV | Recuperación subvoltaje |
| VOL_CELL_OV | 0x1006 | 3650 mV | Protección sobrevoltaje celda |
| VOL_CELL_OVPR | 0x1008 | 3400 mV | Recuperación sobrevoltaje |
| VOL_BALAN_TRIG | 0x100A | 5 mV | Diferencia activa balanceo |
| VOL_SOC_100 | 0x100C | 3460 mV | Voltaje = SOC 100% |
| VOL_SOC_0 | 0x100E | 2900 mV | Voltaje = SOC 0% |
| VOL_CELL_RCV | 0x1010 | 3490 mV | Voltaje carga recomendado |
| VOL_CELL_RFV | 0x1012 | 3380 mV | Voltaje carga flotante |
| VOL_SYS_PWR_OFF | 0x1014 | 2600 mV | Voltaje apagado automático |
| VOL_START_BALAN | 0x1042 | 3420 mV | Voltaje inicio balanceo |

#### Protecciones de corriente (UINT32, unidad mA)

| Campo | Addr | Valor típico | Descripción |
|---|---|---|---|
| CUR_BAT_COC | 0x1016 | 150000 mA | Corriente máx. carga continua |
| CUR_BAT_DOC | 0x101C | 150000 mA | Corriente máx. descarga continua |
| CUR_BALAN_MAX | 0x1024 | 2000 mA | Corriente máxima de balanceo |

#### Protecciones de temperatura (INT32, escala ×0.1 °C)

| Campo | Addr | Valor típico | Descripción |
|---|---|---|---|
| TMP_BAT_COT | 0x1026 | 55.0°C | Sobretemperatura carga |
| TMP_BAT_COTPR | 0x1028 | 50.0°C | Recuperación sobretemperatura carga |
| TMP_BAT_DOT | 0x102A | 60.0°C | Sobretemperatura descarga |
| TMP_BAT_DOTPR | 0x102C | 50.0°C | Recuperación sobretemperatura descarga |
| TMP_BAT_CUT | 0x102E | 1.0°C | Baja temperatura carga |
| TMP_BAT_CUTPR | 0x1030 | 2.0°C | Recuperación baja temperatura carga |
| TMP_MOS_OT | 0x1032 | 80.0°C | Sobretemperatura MOS |
| TMP_MOS_OTPR | 0x1034 | 70.0°C | Recuperación sobretemperatura MOS |

#### Tiempos (UINT32, unidad s)

| Campo | Addr | Valor típico | Descripción |
|---|---|---|---|
| TIM_BAT_COC_DLY | 0x1018 | 3 s | Retardo protección sobrecorriente carga |
| TIM_BAT_COC_PR_DLY | 0x101A | 60 s | Recuperación sobrecorriente carga |
| TIM_BAT_DOC_DLY | 0x101E | 300 s | Retardo protección sobrecorriente descarga |
| TIM_BAT_DOC_PR_DLY | 0x1020 | 60 s | Recuperación sobrecorriente descarga |
| TIM_BAT_SCP_PR_DLY | 0x1022 | 15 s | Recuperación cortocircuito |
| TIM_PRODISCHARGE | 0x1086 | 0 s | Tiempo pre-descarga |
| TIM_SMART_SLEEP | 0x108C | 0 h | Tiempo smart sleep |

#### Switches y otros

| Campo | Addr | Tipo | Valor típico | Descripción |
|---|---|---|---|---|
| BAT_CHARGE_EN | 0x1038 | UINT32 | 1 (ON) | Switch de carga |
| BAT_DISCHARGE_EN | 0x103A | UINT32 | 1 (ON) | Switch de descarga |
| BALAN_EN | 0x103C | UINT32 | 1 (ON) | Switch de balanceo |
| CELL_COUNT | 0x1036 | UINT32 | 16 | Número de celdas configurado |
| CAP_BAT_CELL | 0x103E | UINT32 | 314000 mAh | Capacidad nominal |
| SCP_DELAY | 0x1040 | UINT32 | 30 µs | Retardo protección cortocircuito |
| DEV_ADDR | 0x1084 | UINT32 | 1 | Modbus Unit ID |
| CONFIG_FLAGS | 0x108A | UINT16 | bitmask | Flags de configuración |

---

## 3. JK BMS — Estrategia de lectura por páginas

### 3.1 El problema: lectura paginada en FW v27

El JK BMS FW v27 **no soporta acceso aleatorio** a registros Modbus. La dirección de inicio de cada petición determina una "página" interna del BMS, y los datos devueltos dependen de dicha página. Si se realizan varias peticiones fragmentadas sobre el mismo bloque, cada petición arranca una página diferente y los datos aparecen desplazados.

**Regla empírica:** un desplazamiento de +2 en la dirección de inicio → los datos se desplazan +1 posición en la respuesta.

### 3.2 Solución implementada

**Bloque 0x1400 (Device Info):** una sola petición de 72 words desde `0x1400`.
```python
mem = self._read_block(0x1400, 0x48, chunk_size=72)
```

**Bloque 0x1000 (Config):** primera petición de 68 words cubre `0x1000–0x1043`. Los registros `0x1084–0x108D` requieren una petición dedicada desde su propia página:
```python
mem = self._read_block(0x1000, 0x8E, chunk_size=68)
page1084 = self.read_holding_registers(0x1084, 10)  # DEV_ADDR, timers, flags
```

**Bloque 0x1200 (Realtime):** múltiples rangos naturales + cuatro overrides dedicados:

```python
# Rangos principales (cada uno en una sola petición)
ranges = [
    (0x1200, 16),   # Voltajes celdas 1–16
    (0x1220, 16),   # Stats celdas (zona)
    (0x1240, 16),   # CELL_STA, AVE, VDIF, MAX/MIN cell#
    (0x1260, 32),   # Extras
    (0x1280, 16),   # TEMP_MOS, BAT_VOL, BAT_CURRENT
    (0x12A0, 16),   # SOC, CAP_REMAIN, FULL_CAP, ALARMS
    (0x12B0, 16),   # CYCLE_COUNT, CYCLE_CAP, CHARGE/DISCHARGE_STA
    (0x12C0, 16),   # Timers de recuperación
    (0x12F0, 8),    # Ticks diagnóstico
]

# Overrides dedicados (requieren página específica)
page124A = read_holding_registers(0x124A, 16)   # Resistencias: 0x124A–0x1259
page1288 = read_holding_registers(0x1288, 24)   # TEMP_BAT1 (0x1292), TEMP_BAT2 (0x1293),
                                                 # RUNTIME (0x129E–0x129F)
page12E0 = read_holding_registers(0x12E0, 16)   # TEMP_BAT4 (0x12ED), TEMP_BAT5 (0x12EE)
```

### 3.3 Valores derivados calculados en software

| Campo | Cálculo |
|---|---|
| `BAT_POWER_W` | `BAT_VOL × BAT_CURRENT` |
| `CHARGING_POWER` | `BAT_POWER_W` si > 0, sino 0 |
| `DISCHARGING_POWER` | `abs(BAT_POWER_W)` si < 0, sino 0 |
| `BALAN_STA_TEXT` | Decodificación de `BALAN_STA` (0=Off, 1=Charging, 2=Discharging) |
| `ALARMS_DECODED` | Lista de strings de los bits activos en `ALARMS` |
| `RUNTIME_TEXT` | `ODD_RUN_TIME` formateado como `14d 2h 35m` |
| `ODD_RUN_TIME_TEXT` | Ídem — **este es el campo publicado en HA como uptime** |

---

## 4. Deye Inversor — Mapa Modbus

**Modelo:** SUN-6K-SG05LP1-EU-AM2-P
**Protocolo Modbus:** función 0x03 — acceso directo, sin paginación.

### 4.1 Bloque de identificación (addr 0–9)

| Campo | Addr | Tipo | Descripción |
|---|---|---|---|
| DEVICE_TYPE | 0 | U16 | Tipo de dispositivo (valor: 3) |
| DEVICE_SERIAL | 3 | STR×5 | Número de serie en ASCII |

### 4.2 Energía acumulada (addr 60–100)

| Campo | Addr | Tipo | Gain | Unidad | Descripción |
|---|---|---|---|---|---|
| DAY_PV_ENERGY | 60 | U16 | ÷10 | kWh | Energía PV del día |
| TOTAL_PV_ENERGY | 63 | U32_LE | ÷10 | kWh | Energía PV total acumulada |
| TOTAL_BATTERY_CHARGE | 72 | U32_LE | ÷10 | kWh | Energía carga batería total |
| TOTAL_BATTERY_DISCHARGE | 74 | U32_LE | ÷10 | kWh | Energía descarga batería total |
| DAY_GRID_BUY | 76 | U16 | ÷10 | kWh | Compra red del día |
| DAY_GRID_SELL | 77 | U16 | ÷10 | kWh | Venta red del día |
| TOTAL_GRID_BUY | 78 | U16 | ÷10 | kWh | Compra red total |
| GRID_FREQUENCY | 79 | U16 | ÷100 | Hz | Frecuencia de red |
| TOTAL_GRID_SELL | 80 | U16 | ÷10 | kWh | Venta red total |
| TOTAL_LOAD_ENERGY | 96 | U32_LE | ÷10 | kWh | Energía consumida total |

> `U32_LE`: 32 bits little-endian entre dos registros consecutivos: `value = (reg[1] << 16) | reg[0]`

### 4.3 Live Data 1 (addr 100–154)

| Campo | Addr | Tipo | Gain | Unidad | Descripción |
|---|---|---|---|---|---|
| PV1_VOLTAGE | 109 | U16 | ÷10 | V | Tensión string PV1 |
| PV1_CURRENT | 110 | U16 | ÷10 | A | Corriente string PV1 |
| RADIATOR_TEMP | 111 | I16 | ÷10 | °C | Temperatura radiador inversor |
| GRID_L1_VOLTAGE | 150 | U16 | ÷10 | V | Tensión red fase L1 |

### 4.4 Live Data 2 (addr 160–199)

| Campo | Addr | Tipo | Gain | Unidad | Descripción |
|---|---|---|---|---|---|
| GRID_L1_POWER | 166 | I16 | ×1 | W | Potencia red L1 (+importar, −exportar) |
| GRID_TOTAL_POWER | 169 | I16 | ×1 | W | Potencia red total |
| LOAD_L1_POWER | 173 | U16 | ×1 | W | Potencia carga L1 |
| LOAD_TOTAL_POWER | 175 | U16 | ×1 | W | Potencia carga total |
| BATTERY_TEMP | 182 | I16 | ÷10 −100 | °C | Temperatura batería ¹ |
| BATTERY_VOLTAGE | 183 | U16 | ÷100 | V | Tensión batería |
| BATTERY_SOC | 184 | U16 | ×1 | % | Estado de carga batería |
| PV1_POWER | 186 | U16 | ×1 | W | Potencia PV1 |
| PV2_POWER | 187 | U16 | ×1 | W | Potencia PV2 |
| BATTERY_POWER | 190 | I16 | ×−1 | W | Potencia batería (+desc., −carga) ² |
| BATTERY_CURRENT | 191 | I16 | ÷−100 | A | Corriente batería (+desc., −carga) ² |

> ¹ **BATTERY_TEMP:** el inversor codifica la temperatura como `(T + 100) × 10`. El software aplica: `raw ÷ 10 − 100`. Ejemplo: raw=1157 → 115.7 − 100 = **15.7°C**.
> ² El signo negativo del gain invierte la convención del inversor: el raw positivo indica descarga, el valor resultante positivo también indica descarga.

### 4.5 Correcciones aplicadas respecto al código original

| Campo | Antes | Después | Motivo |
|---|---|---|---|
| RADIATOR_TEMP gain | 100 | **10** | raw=219 → 2.19°C (incorrecto) vs 21.9°C (correcto) |
| LOAD_L1_POWER addr | 172 | **173** | addr 172=0W, addr 173=167W (= LOAD_TOTAL en monofásico) |

---

## 5. Publicación MQTT / Home Assistant Discovery

### 5.1 Estructura de topics

```
# Estado (datos del dispositivo)
jkbms_pre/state              ← JSON con todas las lecturas del BMS
jkbms_pre/availability       ← "online" / "offline"  (retained)

deye_inverter/state          ← JSON con todas las lecturas del inversor
deye_inverter/availability   ← "online" / "offline"  (retained)

# Discovery Home Assistant (formato HA obligatorio, retained)
homeassistant/sensor/geekcomit12/<device>_<field>/config
homeassistant/binary_sensor/geekcomit12/<device>_<field>/config
```

Los topics de estado **no** están bajo el prefijo `homeassistant/` para evitar la mezcla con los topics de discovery.

### 5.2 Formato del payload de estado

El payload de `<device>/state` es un JSON plano con todos los campos del dispositivo:

```json
{
  "BAT_VOL": 53.025,
  "BAT_CURRENT": -6.858,
  "SOC": 86,
  "CELL_VOLTAGES": [3.315, 3.315, 3.315, 3.316, ...],
  "CELL_RESISTANCES": [0.065, 0.066, 0.077, ...],
  "TEMP_MOS": 17.8,
  "TEMP_BAT1": 15.4,
  "CHARGE_STA": 1,
  "DISCHARGE_STA": 1,
  "BAT_CHARGE_EN": 1,
  "ALARMS_DECODED": ["Normal"],
  "ODD_RUN_TIME_TEXT": "14d 2h 35m",
  ...
}
```

### 5.3 Discovery — Sensores (sensor)

Cada campo numérico genera una entidad `sensor` en HA. El discovery payload incluye:

```json
{
  "name": "Bat Vol",
  "unique_id": "geekcomit12_jkbms_bat_vol",
  "state_topic": "jkbms_pre/state",
  "value_template": "{{ value_json.BAT_VOL }}",
  "unit_of_measurement": "V",
  "device_class": "voltage",
  "state_class": "measurement",
  "availability_topic": "jkbms_pre/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "device": {
    "identifiers": ["geekcomit12_jkbms"],
    "name": "JKBMS",
    "manufacturer": "Modbus2MQTT Integration",
    "sw_version": "27",
    "hw_version": "19"
  }
}
```

### 5.4 Discovery — Sensores binarios (binary_sensor)

Los switches de configuración y estados de carga/descarga se publican como `binary_sensor`:

| Entidad HA | Campo JSON | Descripción |
|---|---|---|
| Charge Switch | `BAT_CHARGE_EN` | Switch de carga configurado |
| Discharge Switch | `BAT_DISCHARGE_EN` | Switch de descarga configurado |
| Balance Switch | `BALAN_EN` | Switch de balanceo configurado |
| Charging Active | `CHARGE_STA` | Estado carga en tiempo real |
| Discharging Active | `DISCHARGE_STA` | Estado descarga en tiempo real |

El `value_template` transforma el entero 0/1 a ON/OFF:
```
{{ 'ON' if value_json.CHARGE_STA == 1 else 'OFF' }}
```

El discovery payload incluye `payload_on: "ON"` y `payload_off: "OFF"` explícitamente.

### 5.5 Entidades publicadas en HA

**JK BMS (77 entidades):**
- 16 voltajes de celda (V)
- 16 resistencias de celda (mΩ)
- 5 temperaturas (°C)
- Pack: voltaje, corriente, potencia carga/descarga
- SOC, capacidad restante, capacidad total, ciclos
- Balanceo: corriente, estado
- Estado carga/descarga (sensor + binary_sensor)
- Switches config (binary_sensor)
- Alarmas decodificadas
- Info dispositivo: modelo, HW/SW version, serial, uptime

**Deye Inversor (28 entidades):**
- Energías acumuladas: PV, batería carga/descarga, red compra/venta, carga
- Potencias en tiempo real: PV1, PV2, red, carga, batería
- Tensiones: PV1, red L1, batería
- Corrientes: PV1, batería
- SOC batería, temperatura batería, temperatura radiador
- Frecuencia de red
- Modelo, serial

### 5.6 Availability

- Se publica `online` (retained) tras cada lectura exitosa.
- Se publica `offline` (retained) si `get_all_data()` retorna vacío o lanza excepción.
- HA marca todas las entidades del dispositivo como *unavailable* automáticamente.

---

## 6. Configuración

### 6.1 config.yml

```yaml
broker-mqtt:
  mqtt_server: ${MQTT_SERVER}      # IP del broker
  mqtt_port: ${MQTT_PORT}          # Puerto (default 1883)
  mqtt_user: ${MQTT_USER}
  mqtt_pass: ${MQTT_PASS}
  discovery_prefix: homeassistant  # Prefijo HA Discovery
  node_id: geekcomit12             # Nodo en el topic de discovery

jkbms:
  active: true
  mqtt_subtopic: jkbms_pre         # → topics: jkbms_pre/state, jkbms_pre/availability
  modbus_ip: 192.168.1.136
  modbus_port: 502
  modbus_unit: 1
  query_seconds: 30
  debug_values: false
  firmware_version: 27
  hardware_version: 19

deye_inverter:
  active: true
  mqtt_subtopic: deye_inverter     # → topics: deye_inverter/state, deye_inverter/availability
  modbus_ip: 192.168.1.133
  modbus_port: 502
  modbus_unit: 1
  query_seconds: 10
  debug_values: false
  model: SUN-6K-SG05LP1-EU-AM2-P
```

### 6.2 Variables de entorno (.env)

```
MQTT_SERVER=<IP broker>
MQTT_PORT=1883
MQTT_USER=<usuario>
MQTT_PASS=<contraseña>
```

### 6.3 Ejecución

```bash
# Desarrollo local
cd /Users/nacho/Documents/dev/modbus-to-mqtt
python3 src/main.py

# Diagnóstico JK BMS
python3 src/jkbmsv2_probe.py

# Diagnóstico Deye
python3 src/deye_probe.py

# Dump raw de registros JK BMS (descubrimiento de direcciones)
python3 src/jkbms_raw_dump.py
```
