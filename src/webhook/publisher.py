import ipaddress
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger("modbus2mqtt.webhook")


def _host_is_ip(url: str) -> bool:
    """True only if the URL's host is a literal IP address (v4 or v6)."""
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        ipaddress.ip_address(hostname)
        return True
    except (ValueError, Exception):
        return False


class WebhookPublisher:
    """POSTs each device's state payload to a second HTTP endpoint, mirroring
    the same plain JSON sent to the MQTT state topic. If the configured URL's
    host is not a literal IP address (e.g. still the placeholder), the
    publisher stays disabled and never attempts a request.
    """

    def __init__(self, url: str = None, active: bool = False, timeout_seconds: int = 5):
        self.url = url
        self.timeout = timeout_seconds
        self.enabled = bool(active and url and _host_is_ip(url))

        if active and url and not self.enabled:
            logger.warning(
                f"Webhook configured but URL host is not a valid IP ('{url}'); "
                "webhook forwarding disabled until it's set to a real IP."
            )
        elif self.enabled:
            logger.info(f"Webhook forwarding enabled -> {self.url}")

    def send(self, device_name: str, data: dict):
        if not self.enabled:
            return

        try:
            resp = requests.post(self.url, json=data, timeout=self.timeout)
            if resp.status_code >= 400:
                logger.warning(f"Webhook POST for {device_name} returned HTTP {resp.status_code}")
            else:
                logger.debug(f"Webhook POST for {device_name} ok ({resp.status_code})")
        except Exception as e:
            logger.warning(f"Error sending {device_name} data to webhook: {e}")
