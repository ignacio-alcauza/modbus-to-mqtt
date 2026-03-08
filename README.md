# Modbus to MQTT Bridge

Python service to read data from Modbus TCP devices (like JK BMS and Huawei SUN2000 Inverters) and publish it to an MQTT Broker (like Home Assistant).

## Project Structure

```text
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env                 # Secrets (not tracked in git)
├── config.yml           # General configuration
└── src/                 # Application source code
    ├── main.py
    ├── devices/
    │   ├── jkbms.py
    │   └── deye.py
    ├── mqtt/
    │   └── publisher.py
    └── utils/
        ├── logger.py
        └── modbus.py
```

## Setup & Configuration

1. Copy `.env.example` to `.env` and configure your MQTT broker credentials.
2. Edit `config.yml` to define your devices, IPs, and polling intervals.

## Running Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

## Running with Docker (Recommended for 24/7)

```bash
docker-compose up -d --build
docker-compose logs -f
```
