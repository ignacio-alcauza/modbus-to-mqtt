# Requerimiento: corrección de la potencia consumida por la vivienda

## 1. Objetivo

Corregir la lectura de potencia consumida por la vivienda que entrega el
productor Modbus-to-MQTT/Webhook del inversor Deye.

Las comprobaciones directas realizadas contra el inversor han confirmado que
los registros Modbus 173 y 175 no representan el consumo real de la vivienda.
Estos registros pueden oscilar alrededor de cero y representar otra magnitud
del flujo energético.

El consumo real de la vivienda se encuentra en el registro Modbus **176**.

## 2. Cambio requerido

Añadir una nueva medida al mapa de registros Deye, dentro del grupo
`Live_Data_2`:

```python
{
    "name": "HOUSE_LOAD_POWER",
    "address": 176,
    "count": 1,
    "type": "U16",
    "unit": "W",
}
```

El bloque `Live_Data_2` ya realiza la lectura conjunta de los registros
160–199, por lo que no debería ser necesaria una lectura Modbus adicional.

## 3. Contrato del nuevo campo

El productor deberá incluir en la trama enviada por webhook el siguiente campo:

```json
{
  "HOUSE_LOAD_POWER": 238
}
```

Condiciones del campo:

- Nombre exacto: `HOUSE_LOAD_POWER`.
- Origen: registro Modbus 176.
- Tipo lógico: entero sin signo de 16 bits (`U16`).
- Unidad: vatios (`W`).
- No se debe calcular a partir de otros contadores.
- El valor `0xFFFF` se seguirá interpretando como ausencia de dato.

## 4. Compatibilidad

El cambio debe ser estrictamente aditivo.

No se modificarán ni eliminarán los siguientes campos existentes:

```text
LOAD_L1_POWER
LOAD_TOTAL_POWER
GRID_TOTAL_POWER
PV2_POWER
BATTERY_POWER
```

Tampoco se modificarán:

- Los topics MQTT existentes.
- Los identificadores de dispositivo.
- La publicación de disponibilidad.
- Los intervalos de lectura.
- La conexión con Home Assistant.
- El formato de `_observed_at`.
- El valor actual de `_schema_version`.

Esta ampliación se considera compatible con el contrato existente y no requiere
incrementar la versión del esquema.

## 5. MQTT y Home Assistant

`HOUSE_LOAD_POWER` debe estar presente en el JSON de estado y en la petición
webhook dirigida a Pulso.

La presencia de una propiedad adicional en el JSON MQTT no afecta a las
entidades existentes de Home Assistant, que continuarán leyendo sus campos
actuales.

No es necesario crear una nueva entidad mediante MQTT Discovery. Si el
productor genera automáticamente una entidad por cada registro, se recomienda
permitir que el registro tenga una propiedad como:

```python
"discovery": False
```

y omitirlo únicamente de la generación de discovery, sin retirarlo del payload
MQTT ni del webhook.

## 6. Datos que no deben publicarse

El cambio no debe provocar la publicación de información interna de depuración.

Se mantendrán las reglas actuales:

- No incluir `_raw_data` en MQTT.
- No incluir `_raw_data` en el webhook.
- No incluir credenciales, contraseñas, PIN ni otros secretos.

## 7. Validación funcional

Durante las pruebas se tomarán varias lecturas consecutivas y se comparará el
nuevo campo con el balance energético:

```text
HOUSE_LOAD_POWER ≈ PV2_POWER + GRID_TOTAL_POWER + BATTERY_POWER
```

Convención de signos utilizada:

- `GRID_TOTAL_POWER > 0`: importación desde la red.
- `GRID_TOTAL_POWER < 0`: vertido a la red.
- `BATTERY_POWER > 0`: descarga de la batería.
- `BATTERY_POWER < 0`: carga de la batería.

Puede existir una diferencia pequeña debido a pérdidas de conversión,
autoconsumo del inversor, redondeo o sincronización de las medidas. No se debe
forzar matemáticamente que ambas cantidades sean idénticas.

### Ejemplo real observado

```text
PV2_POWER          = 139 W
GRID_TOTAL_POWER   = -49 W
BATTERY_POWER      = 159 W
Balance calculado  = 249 W
HOUSE_LOAD_POWER   = 238 W
```

La diferencia aproximada de 11 W es razonable. En esa misma lectura, los
registros 173/175 devolvían 287 W y no representaban el consumo doméstico real.

## 8. Pruebas de aceptación

El cambio se considerará aceptado cuando se verifique lo siguiente:

1. `HOUSE_LOAD_POWER` está presente en las tramas Deye.
2. Su valor coincide con la lectura directa del registro 176.
3. El valor se expresa como un entero en vatios.
4. El campo llega correctamente al webhook en cada ciclo de publicación.
5. Las entidades MQTT existentes de Home Assistant siguen funcionando.
6. No se han modificado los topics ni los identificadores existentes.
7. No se publica `_raw_data`.
8. No se publican secretos.
9. `_observed_at` conserva el formato RFC 3339 en UTC terminado en `Z`.
10. `_schema_version` mantiene su valor actual.
11. El healthcheck del productor continúa siendo correcto.
12. La ejecución continuada no genera errores nuevos en los logs.

## 9. Orden de despliegue

El despliegue debe coordinarse en este orden:

1. Preparar y probar el cambio en el productor sin activarlo todavía en
   producción.
2. Adaptar Pulso para reconocer `HOUSE_LOAD_POWER` como telemetría.
3. Desplegar la versión compatible de Pulso.
4. Desplegar o reiniciar el productor con el nuevo campo.
5. Verificar la recepción del campo en Pulso.
6. Comparar durante varios minutos `HOUSE_LOAD_POWER` con el resto del balance.

Este orden es importante porque, antes de que Pulso reconozca expresamente el
nuevo campo, podría clasificarlo como una propiedad de configuración variable.

## 10. Resultado esperado en Pulso

Una vez completados ambos despliegues:

- La tarjeta `Casa` utilizará `HOUSE_LOAD_POWER`.
- Pulso conservará separadas las medidas reales de FV, red, batería y vivienda.
- Las pequeñas diferencias se tratarán como pérdidas o regulación, sin
  incorporarlas artificialmente al consumo doméstico.
- Los valores originales recibidos del inversor seguirán disponibles para
  diagnóstico.

