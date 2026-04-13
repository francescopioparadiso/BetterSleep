"""Shared helpers for simulation scripts."""

import json
import os

import requests


def load_json_file(path):
    with open(path, "r") as handle:
        return json.load(handle)


def build_url(base, path):
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def get_user_service_endpoint(catalog_url, timeout=5):
    response = requests.get(build_url(catalog_url, "getEndpointUserService"), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload.get("endpoint")


def apply_runtime_overrides(config):
    """Allow local task runs to override Docker-only hostnames via env vars."""
    catalog_url = os.environ.get("SIMULATION_CATALOG_URL")
    mqtt_broker = os.environ.get("SIMULATION_MQTT_BROKER")
    mqtt_port = os.environ.get("SIMULATION_MQTT_PORT")

    if catalog_url:
        config.setdefault("catalog", {})["url"] = catalog_url

    if mqtt_broker:
        config.setdefault("mqtt", {})["broker"] = mqtt_broker

    if mqtt_port:
        try:
            config.setdefault("mqtt", {})["port"] = int(mqtt_port)
        except ValueError:
            pass

    return config
