#!/usr/bin/env python3
"""
Deye Inverter Write Probe — Verifica que la escritura Modbus (FC06) llega al
inversor, usando el registro 249 (documentado como "reservado/sin usar",
confirmado en vivo = 0, sin referencia en Deye Cloud ni en ninguna función
conocida — ver doc/PARAMS_CONFIG_DEYE.md §A.1).

Secuencia (reversible, sin tocar nada funcional):
    1. Leer 249        -> debe dar el valor actual (esperado: 0)
    2. Escribir 249=1   -> FC06
    3. Releer 249       -> debe dar 1 (confirma que la escritura llegó)
    4. Restaurar 249=valor original
    5. Releer 249       -> debe volver al valor original

Uso:
    cd /Users/nacho/Documents/dev/modbus-to-mqtt
    python3 src/deye_write_probe.py                    # FC06, addr 249
    python3 src/deye_write_probe.py --fc16              # FC16, addr 249
    python3 src/deye_write_probe.py --fc16 --addr 267   # FC16, addr arbitraria
                                                         # (nudge +1 sobre el valor actual, revertido al final)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from utils.modbus import BaseModbusClient

DEYE_IP = '192.168.1.133'
DEYE_PORT = 502
DEYE_UNIT = 1
DEFAULT_ADDR = 249

RST = '\033[0m'; B = '\033[1m'
GRN = '\033[92m'; YEL = '\033[93m'; RED = '\033[91m'; CYN = '\033[96m'


def read_one(client, addr):
    regs = client.read_holding_registers(addr, 1)
    return regs[0] if regs else None


def main():
    use_fc16 = '--fc16' in sys.argv
    fc_label = "FC16 (write_registers)" if use_fc16 else "FC06 (write_register)"

    test_addr = DEFAULT_ADDR
    if '--addr' in sys.argv:
        test_addr = int(sys.argv[sys.argv.index('--addr') + 1])

    print(f"\n{B}{CYN}{'='*70}{RST}")
    print(f"  {B}Deye Write Probe — registro {test_addr}{RST}")
    print(f"  {DEYE_IP}:{DEYE_PORT} · Unit {DEYE_UNIT} · {fc_label}")
    print(f"{B}{CYN}{'='*70}{RST}\n")

    client = BaseModbusClient(host=DEYE_IP, port=DEYE_PORT, unit_id=DEYE_UNIT)

    try:
        with client:
            original = read_one(client, test_addr)
            if original is None:
                print(f"  {RED}ERROR: no se pudo leer el registro {test_addr}. Abortando.{RST}")
                sys.exit(1)
            print(f"  1. Valor original en {test_addr}: {B}{original}{RST}")

            # Nudge de +1 sobre el valor actual (revertido al final), en vez de
            # un valor fijo — así sirve tanto para el registro de prueba (249,
            # siempre 0) como para un registro "vivo" con valor real.
            test_value = (original + 1) % 0x10000

            print(f"  2. Escribiendo {test_value} en {test_addr} ({fc_label})...")
            if use_fc16:
                ok = client.write_registers(test_addr, [test_value])
            else:
                ok = client.write_register(test_addr, test_value)
            if not ok:
                print(f"  {RED}ERROR: la escritura {fc_label} falló (gateway probablemente solo-lectura).{RST}")
                sys.exit(1)
            print(f"  {GRN}   Escritura aceptada por el gateway.{RST}")

            readback = read_one(client, test_addr)
            print(f"  3. Releyendo {test_addr}: {B}{readback}{RST}")

            if readback != test_value:
                print(f"  {RED}ERROR: el valor releído ({readback}) no coincide con lo escrito ({test_value}).{RST}")
                print(f"  {RED}No se restaura automáticamente — revisar manualmente.{RST}")
                sys.exit(1)

            print(f"  {GRN}   Confirmado: la escritura llegó al inversor.{RST}")

            print(f"  4. Restaurando valor original ({original}) en {test_addr}...")
            if use_fc16:
                ok = client.write_registers(test_addr, [original])
            else:
                ok = client.write_register(test_addr, original)
            if not ok:
                print(f"  {RED}ERROR: no se pudo restaurar el valor original. Registro queda en {test_value}.{RST}")
                sys.exit(1)

            final = read_one(client, test_addr)
            print(f"  5. Releyendo {test_addr}: {B}{final}{RST}")

            if final == original:
                print(f"\n  {GRN}{B}✓ PRUEBA OK — escritura Modbus ({fc_label}) funciona y el registro quedó restaurado.{RST}\n")
            else:
                print(f"\n  {RED}{B}✗ El registro no quedó restaurado (quedó en {final}, original era {original}).{RST}\n")
                sys.exit(1)

    except ConnectionError as e:
        print(f"\n  {RED}{B}ERROR conectando a {DEYE_IP}:{DEYE_PORT}{RST}\n  {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
