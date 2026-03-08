import logging
import json
import paho.mqtt.client as mqtt

logger = logging.getLogger("modbus2mqtt.mqtt")

class MQTTPublisher:
    def __init__(self, host: str, port: int, user: str = None, password: str = None):
        self.host = host
        self.port = port
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        
        if user and password:
            self.client.username_pw_set(user, password)
            
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
        else:
            logger.error(f"Failed to connect to MQTT broker, reason code: {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        logger.warning(f"Disconnected from MQTT broker, reason code: {reason_code}")

    def connect(self):
        try:
            self.client.connect(self.host, self.port, 60)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish_data(self, topic: str, data: dict):
        """Publish device data as a JSON payload."""
        try:
            payload = json.dumps(data)
            result = self.client.publish(topic, payload, qos=1)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published data to {topic}: {payload}")
            else:
                logger.error(f"Failed to publish to {topic}, return code: {result.rc}")
        except Exception as e:
            logger.error(f"Error publishing data to {topic}: {e}")
