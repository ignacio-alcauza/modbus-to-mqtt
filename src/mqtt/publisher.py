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

    def publish_discovery(self, device_id: str, device_name: str, state_topic: str, sensors: list, discovery_prefix: str = "homeassistant", node_id: str = None):
        """Publish Home Assistant MQTT Discovery configuration."""
        device_info = {
            "identifiers": [device_id],
            "name": device_name,
            "manufacturer": "Modbus2MQTT Integration"
        }
        
        for sensor in sensors:
            # Topic format: <discovery_prefix>/<component>/<node_id>/<object_id>/config
            # Home Assistant strict regex: node_id and object_id cannot contain slashes.
            if node_id:
                safe_node_id = node_id.replace("/", "_")
                object_id = f"{device_name.lower().replace(' ', '_')}_{sensor['id']}"
                discovery_topic = f"{discovery_prefix}/sensor/{safe_node_id}/{object_id}/config"
            else:
                safe_device_id = device_id.replace("/", "_")
                discovery_topic = f"{discovery_prefix}/sensor/{safe_device_id}/{sensor['id']}/config"
            
            payload = {
                "name": sensor['name'],
                "unique_id": f"{device_id}_{sensor['id']}".replace("/", "_"),
                "state_topic": state_topic,
                "value_template": sensor.get('value_template'),
                "device": device_info
            }
            
            if sensor.get('unit'):
                payload["unit_of_measurement"] = sensor['unit']
            if sensor.get('device_class'):
                payload["device_class"] = sensor['device_class']
                if sensor['device_class'] == "energy_storage":
                    payload["device_class"] = "energy" # Fallback if energy_storage isn't perfectly supported
                
            try:
                self.client.publish(discovery_topic, json.dumps(payload), retain=True)
                logger.debug(f"Published discovery to {discovery_topic}")
            except Exception as e:
                logger.error(f"Failed to publish discovery for {sensor['id']}: {e}")
