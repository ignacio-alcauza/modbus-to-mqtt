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

    def publish_raw(self, topic: str, payload: str, retain: bool = False):
        """Publish a raw string payload."""
        try:
            result = self.client.publish(topic, payload, qos=1, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Failed to publish to {topic}, return code: {result.rc}")
        except Exception as e:
            logger.error(f"Error publishing to {topic}: {e}")

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

    def publish_discovery(self, device_id: str, device_name: str, state_topic: str,
                          sensors: list, discovery_prefix: str = "homeassistant",
                          node_id: str = None, sw_version: str = None, hw_version: str = None,
                          availability_topic: str = None):
        """Publish Home Assistant MQTT Discovery configuration."""
        device_info = {
            "identifiers": [device_id],
            "name": device_name,
            "manufacturer": "Modbus2MQTT Integration"
        }
        if sw_version:
            device_info["sw_version"] = str(sw_version)
        if hw_version:
            device_info["hw_version"] = str(hw_version)

        for sensor in sensors:
            component = sensor.get('component', 'sensor')

            # Topic: <discovery_prefix>/<component>/<node_id>/<object_id>/config
            if node_id:
                safe_node_id = node_id.replace("/", "_")
                object_id = f"{device_name.lower().replace(' ', '_')}_{sensor['id']}"
                discovery_topic = f"{discovery_prefix}/{component}/{safe_node_id}/{object_id}/config"
            else:
                safe_device_id = device_id.replace("/", "_")
                discovery_topic = f"{discovery_prefix}/{component}/{safe_device_id}/{sensor['id']}/config"

            payload = {
                "name": sensor['name'],
                "unique_id": f"{device_id}_{sensor['id']}".replace("/", "_"),
                "state_topic": state_topic,
                "value_template": sensor.get('value_template'),
                "device": device_info
            }

            if availability_topic:
                payload["availability_topic"] = availability_topic
                payload["payload_available"] = "online"
                payload["payload_not_available"] = "offline"

            # Pass through all sensor-specific fields
            passthrough = [
                "unit_of_measurement", "device_class", "state_class", "icon",
                "expire_after", "force_update", "payload_on", "payload_off",
            ]
            for key in passthrough:
                if key in sensor:
                    payload[key] = sensor[key]
                elif key == "unit_of_measurement" and "unit" in sensor:
                    payload[key] = sensor["unit"]

            # Smart state_class defaults when missing
            if "state_class" not in payload and payload.get("device_class") in (
                "voltage", "current", "power", "temperature", "battery"
            ):
                payload["state_class"] = "measurement"
            elif "state_class" not in payload and payload.get("device_class") == "energy":
                payload["state_class"] = "total_increasing"

            try:
                json_payload = json.dumps(payload)
                logger.info(f"Discovery -> {discovery_topic}")
                self.client.publish(discovery_topic, json_payload, retain=True, qos=1)
            except Exception as e:
                logger.error(f"Failed to publish discovery for {sensor['id']}: {e}")
