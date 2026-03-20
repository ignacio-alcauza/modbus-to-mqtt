import sys, os
sys.path.insert(0, os.path.abspath('src'))

from devices.jkbmsv2 import JKBMSV2Client

def test_v2_discovery_and_data():
    client = JKBMSV2Client(host='127.0.0.1')
    
    print("--- Testing Discovery Sensors ---")
    sensors = client.get_discovery_sensors()
    print(f"Total sensors: {len(sensors)}")
    
    binary_sensors = [s for s in sensors if s.get('component') == 'binary_sensor']
    print(f"Binary sensors found: {len(binary_sensors)}")
    for b in binary_sensors:
        print(f"  - {b['name']} (ID: {b['id']}, Component: {b['component']})")
        assert b['component'] == 'binary_sensor'
        assert 'payload_on' in b
        assert 'payload_off' in b

    volt_sensors = [s for s in sensors if s.get('device_class') == 'voltage']
    print(f"Voltage sensors found: {len(volt_sensors)}")
    # Should have BAT_VOL, and 16 cell voltages
    # and maybe some config voltages
    
    print("\n--- Testing Data Flattening (Mock Data) ---")
    # Mock some methods to return sample data
    client.read_device_info_block = lambda: {'SW_VERSION': 'v27', 'SERIAL_NO': '12345'}
    client.read_realtime_block = lambda: {'SOC': 95, 'BAT_VOL': 53.5}
    client.read_config_block = lambda: {'BAT_CHARGE_EN': 1, 'BALAN_EN': 0}
    
    data = client.get_all_data()
    print(f"Flattened keys: {list(data.keys())}")
    
    assert data['SOC'] == 95
    assert data['FIRMWARE_VERSION'] == 'v27'
    assert data['BAT_CHARGE_EN'] == 1
    assert data['BALAN_EN'] == 0
    assert '_raw_data' in data
    
    print("\n✅ Verification SUCCESS")

if __name__ == "__main__":
    test_v2_discovery_and_data()
