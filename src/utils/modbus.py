import time
import struct
import logging
from pymodbus.client import ModbusTcpClient

logger = logging.getLogger("modbus2mqtt.modbus")

class BaseModbusClient:
    """Base client for reading data via Modbus TCP."""

    DEFAULT_TIMEOUT = 10
    MAX_RETRIES = 3
    RETRY_DELAY = 1

    def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: int = DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._client = None

    def connect(self) -> bool:
        self._client = ModbusTcpClient(host=self.host, port=self.port, timeout=self.timeout)
        if not self._client.connect():
            logger.error(f"Failed to connect to {self.host}:{self.port}")
            return False
        logger.info(f"Connected to {self.host}:{self.port} (Unit ID: {self.unit_id})")
        return True

    def disconnect(self):
        if self._client:
            self._client.close()
            logger.info(f"Disconnected from {self.host}:{self.port}")

    def read_holding_registers(self, address: int, count: int, retries: int = MAX_RETRIES):
        for attempt in range(retries):
            try:
                # Handle pymodbus version differences
                try:
                    res = self._client.read_holding_registers(address, count=count, slave=self.unit_id)
                except TypeError:
                    res = self._client.read_holding_registers(address, count=count, device_id=self.unit_id)

                if res and not res.isError():
                    return res.registers
                
                if res and res.isError():
                    logger.warning(f"Modbus error reading address {address} (count={count}): {res}")

            except Exception as e:
                logger.warning(f"Unexpected error reading address {address} (attempt {attempt + 1}/{retries}): {e}")

            if attempt < retries - 1:
                time.sleep(self.RETRY_DELAY)

        return None
    
    def __enter__(self):
        if not self.connect():
            raise ConnectionError(f"Cannot connect to Modbus TCP device at {self.host}:{self.port}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def get_discovery_sensors(self) -> list:
        """Return a list of HA MQTT discovery definitions for this device."""
        return []
