import time
import os
import sys
import json
import yaml
import logging
from datetime import datetime
from dotenv import load_dotenv

from utils.logger import configure_logging
from devices.jkbms import JKBMSClient
from devices.deye import HuaweiSUN2000Client
from mqtt.publisher import MQTTPublisher

logger = configure_logging(logging.INFO)

def load_config():
    """Load configuration from config.yml and .env."""
    load_dotenv()
    
    config_path = os.getenv("CONFIG_PATH", "config.yml")
    if not os.path.exists(config_path):
        logger.error(f"Configuration file {config_path} not found.")
        sys.exit(1)
        
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    return config

def write_debug_file(device_name: str, data: dict):
    """Write device data to a local JSON file for debugging."""
    try:
        os.makedirs("logs", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs/{device_name}_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.debug(f"Saved debug file: {filename}")
    except Exception as e:
        logger.error(f"Failed to write debug file for {device_name}: {e}")

def main():
    # Handle Docker healthcheck
    if "--healthcheck" in sys.argv:
        hb_file = "/tmp/heartbeat"
        if os.path.exists(hb_file):
            if time.time() - os.path.getmtime(hb_file) < 150:
                sys.exit(0)
        sys.exit(1)

    # Initial heartbeat for Docker healthcheck
    try:
        with open("/tmp/heartbeat", "w") as f:
            f.write(str(int(time.time())))
    except Exception as e:
        logger.error(f"Failed to create initial heartbeat file: {e}")

    config = load_config()
    
    # Init MQTT
    mqtt_host = os.getenv("MQTT_SERVER")
    mqtt_port = int(os.getenv("MQTT_PORT", 1883))
    mqtt_user = os.getenv("MQTT_USER")
    mqtt_pass = os.getenv("MQTT_PASS")
    
    if not mqtt_host:
        logger.error("MQTT_SERVER not found in .env. Exiting.")
        sys.exit(1)
        
    publisher = MQTTPublisher(host=mqtt_host, port=mqtt_port, user=mqtt_user, password=mqtt_pass)
    if not publisher.connect():
        sys.exit(1)

    devices = []
    
    # Init devices based on config
    
    # Get base MQTT topic
    broker_conf = config.get("broker-mqtt", {})
    base_topic = broker_conf.get("homeassistant_mqtt_topic", "homeassistant")
    
    jkbms_conf = config.get("jkbms", {})
    if jkbms_conf.get("active", False):
        jkbms = JKBMSClient(
            host=jkbms_conf.get("modbus_ip"),
            port=jkbms_conf.get("modbus_port", 502),
            unit_id=jkbms_conf.get("modbus_unit", 1)
        )
        
        # Build topic dynamically with /state
        subtopic = jkbms_conf.get("mqtt_subtopic", "jkbms")
        full_topic = f"{base_topic}/{subtopic}/state"
        
        devices.append({
            "name": "jkbms",
            "client": jkbms,
            "topic": full_topic,
            "interval": jkbms_conf.get("query_seconds", 30),
            "debug": jkbms_conf.get("debug_values", False),
            "firmware_version": jkbms_conf.get("firmware_version"),
            "hardware_version": jkbms_conf.get("hardware_version"),
            "last_run": 0
        })
        logger.info(f"Initialized JKBMS at {jkbms.host}:{jkbms.port} (Topic: {full_topic}, Debug: {jkbms_conf.get('debug_values', False)})")

    deye_conf = config.get("deye_inverter", {})
    if deye_conf.get("active", False):
        deye = HuaweiSUN2000Client(
            host=deye_conf.get("modbus_ip"),
            port=deye_conf.get("modbus_port", 502),
            unit_id=deye_conf.get("modbus_unit", 1)
        )
        
        # Build topic dynamically with /state
        subtopic = deye_conf.get("mqtt_subtopic", "deye_inverter")
        full_topic = f"{base_topic}/{subtopic}/state"
        
        devices.append({
            "name": "deye_inverter",
            "client": deye,
            "topic": full_topic,
            "interval": deye_conf.get("query_seconds", 30),
            "debug": deye_conf.get("debug_values", False),
            "firmware_version": deye_conf.get("firmware_version"),
            "hardware_version": deye_conf.get("hardware_version"),
            "last_run": 0
        })
        logger.info(f"Initialized Deye Inverter at {deye.host}:{deye.port} (Topic: {full_topic}, Debug: {deye_conf.get('debug_values', False)})")

    if not devices:
        logger.warning("No active devices found in config.yml. Exiting.")
        sys.exit(0)

    # Publish MQTT Discovery Configs for Home Assistant
    discovery_prefix = broker_conf.get("discovery_prefix", "homeassistant")
    for dev in devices:
        sensors = dev["client"].get_discovery_sensors()
        if sensors:
            # Create a unique device ID without slashes so HA discovery doesn't break
            # Node ID must be alphanumeric and underscore
            node_name = base_topic.split("/")[-1] if "/" in base_topic else base_topic
            device_id = f"{node_name}_{dev['name']}"
            
            # Augment sensors with hardware and firmware if present
            if dev.get("firmware_version"):
                sensors.append({
                    "id": "firmware_version",
                    "name": "Firmware Version",
                    "value_template": "{{ value_json.FIRMWARE_VERSION }}",
                    "device_class": None
                })
            if dev.get("hardware_version"):
                sensors.append({
                    "id": "hardware_version",
                    "name": "Hardware Version",
                    "value_template": "{{ value_json.HARDWARE_VERSION }}",
                    "device_class": None
                })
            
            logger.info(f"Publishing HA Discovery for {dev['name']} ({len(sensors)} sensors)")

            try:
                publisher.publish_discovery(
                    device_id=device_id,
                    device_name=dev["name"].upper(),
                    state_topic=dev["topic"],
                    sensors=sensors,
                    discovery_prefix=discovery_prefix,
                    node_id=node_name,
                    sw_version=dev.get("firmware_version"),
                    hw_version=dev.get("hardware_version")
                )
            except Exception as e:
                logger.error(f"Failed to publish discovery for {dev['name']}: {e}")

    logger.info("Starting main loop...")
    
    try:
        while True:
            # Update heartbeat file for Docker healthcheck
            try:
                # touching file is enough to update mtime
                os.utime("/tmp/heartbeat", None)
            except Exception:
                try:
                    with open("/tmp/heartbeat", "w") as f:
                        f.write(str(int(time.time())))
                except:
                    pass

            current_time = time.time()
            
            for dev in devices:
                if current_time - dev["last_run"] >= dev["interval"]:
                    logger.debug(f"Querying {dev['name']}...")
                    client = dev["client"]
                    
                    try:
                        with client:
                            data = client.get_all_data()
                            if data:
                                # Write debug file (includes _raw_data)
                                if dev["debug"]:
                                    write_debug_file(dev["name"], data)
                                
                                # Remove _raw_data before sending to MQTT
                                data.pop("_raw_data", None)
                                
                                # Inject static version config into data payload
                                if dev.get("firmware_version"):
                                    data["FIRMWARE_VERSION"] = str(dev["firmware_version"])
                                if dev.get("hardware_version"):
                                    data["HARDWARE_VERSION"] = str(dev["hardware_version"])
                                
                                # Send data to MQTT
                                publisher.publish_data(dev["topic"], data)
                            else:
                                logger.warning(f"No data received from {dev['name']}")
                    except Exception as e:
                        logger.error(f"Error querying {dev['name']}: {e}")
                        
                    dev["last_run"] = time.time()
                    
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        publisher.disconnect()

if __name__ == "__main__":
    main()
