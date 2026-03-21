"""Shared helpers for simulation scripts."""

import json

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

