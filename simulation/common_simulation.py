"""Shared helpers for simulation scripts."""

import json
from urllib.parse import urlparse, urlunparse

import requests


def load_json_file(path):
    with open(path, "r") as handle:
        return json.load(handle)


def build_url(base, path):
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def normalize_service_endpoint(endpoint, fallback_host="localhost"):
    parsed = urlparse(endpoint)
    host = parsed.hostname

    # Docker service names are resolvable only inside the compose network.
    if host and "." not in host and host not in {"localhost", "127.0.0.1"}:
        netloc = fallback_host
        if parsed.port:
            netloc = f"{fallback_host}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))

    return endpoint


def get_user_service_endpoint(catalog_url, timeout=5):
    response = requests.get(build_url(catalog_url, "getEndpointUserService"), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    endpoint = payload.get("endpoint")
    return normalize_service_endpoint(endpoint) if endpoint else endpoint
