# Technical Documentation: JK BMS Modbus TCP Integration
**Model**: PB2A16S20P (16S 200A)  
**Interface**: Modbus TCP via RS485-to-Ethernet Gateway

## 1. Connection Parameters
- **BMS IP**: `192.168.1.136`
- **Port**: `502`
- **Slave ID (Unit ID)**: `1`
- **Modbus Function**: Reading Holding Registers (0x03)

## 2. Register Mapping
All addresses are in **Hexadecimal**. Range `0x1200 - 0x12BF` contains all monitoring and basic configuration data.

### 2.1 Cell Monitoring (0x1200+)
| Parameter | Address | Count | Type | Scaling | Unit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Cell Voltages (1-16) | `0x1200` | 16 | UINT16 | 1.0 | mV |
| Cell Resistances (1-16) | `0x1225` | 16 | UINT16 | 0.001 | mΩ |

### 2.2 Battery Monitoring (0x1280+)
| Parameter | Address | Count | Type | Scaling | Unit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Battery Voltage | `0x1289` | 1 | UINT16 | 0.001 | V |
| Battery Current | `0x128A` | 2 | INT32_SWAP | 0.001 | A |
| Battery Power | `0x128C` | 2 | INT32_SWAP | 1.0 | W |
| Temperature T1 | `0x128E` | 1 | INT16 | 0.1 | °C |
| Temperature T2 | `0x128F` | 1 | INT16 | 0.1 | °C |
| SOC Percentage | `0x1293` | 1 | UINT16 | 1.0 | % |
| Remaining Cap | `0x1294` | 2 | UINT32 | 0.001 | Ah |
| Full Capacity | `0x1296` | 2 | UINT32 | 0.001 | Ah |
| Cell Volt Diff | `0x129E` | 1 | UINT16 | 0.001 | V |
| BMS Uptime | `0x129E` | 2 | UINT32 | 1.0 | s |

### 2.3 Status & Alarms (0x12A0+)
| Parameter | Address | Type | Bit/Byte | Unit |
| :--- | :--- | :--- | :--- | :--- |
| Charge Switch | `0x12A0` | UINT8_HIGH | High Byte | ON/OFF |
| Discharge Switch | `0x12A0` | UINT8_LOW | Low Byte | ON/OFF |
| Alarm Bitmask | `0x12A1` | UINT32_SWAP | 32-bit | Flags |
| MOSFET Temp | `0x12BC` | INT16 | 0.1 | °C |
| Temperature T4 | `0x12BD` | INT16 | 0.1 | °C |
| Temperature T5 | `0x12BE` | INT16 | 0.1 | °C |

## 3. Data Decoding Logic
- **INT32_SWAP**: 32-bit integer where words are swapped. `(Reg1 << 16) + Reg0` in Little-Endian platforms, but typically represented as swapped words in JK BMS firmware.
- **UINT8_HIGH/LOW**: Large 16-bit registers that pack two 8-bit status flags.
- **Scaling**: Standard multipliers applied after decoding to match real-world units (e.g., `*0.001` for Ah/V).

## 4. Alarm Bitmask Definition
The register `0x12A1` (32-bit) uses the following bits for error reporting:
- **Bit 0**: Resistance anomaly
- **Bit 1**: Cell undervoltage
- **Bit 2**: Cell overvoltage
- **Bit 3**: Charge over-current
- **Bit 4**: Discharge over-current
- **Bit 5**: Discharge short-circuit
- **Bit 6**: Cell over-temperature
- **Bit 7**: MOS over-temperature
- **Bit 8**: Cell low-temperature
- **Bit 9**: Internal communication anomaly
- **Bit 10**: Cell differential anomaly
- **Bit 11**: Discharge MOS anomaly
- **Bit 12**: Charge MOS anomaly
- **Bit 13**: Balance MOS anomaly
- **Bit 14**: BMS over-temperature
- **Bit 15**: Internal battery anomaly

## 5. Implementation Strategy
To ensure stability and compatibility, the client:
1.  **Reads in blocks**: Avoids reading illegal addresses or gaps by chunking requests (e.g., `0x1200`, `0x1240`, `0x1280`).
2.  **Dynamic Decoding**: Uses a type-based decoding function to handle varying register widths and byte orders.
3.  **Visual Reporting**: Generates a formatted CLI report for easy human verification.

---
*Documentation generated on 2026-03-07 based on empirical analysis of model PB2A16S20P.* 
