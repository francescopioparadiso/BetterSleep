import json

import cherrypy


def json_error_page(status, message, traceback, version):
    """Override CherryPy HTTPError to return JSON instead of HTML."""
    cherrypy.response.headers["Content-Type"] = "application/json"

    # Status arriva come "404 Not Found" → prendiamo solo il numero
    try:
        status_code = int(status.split(" ")[0])
    except (ValueError, IndexError):
        status_code = 500

    return json.dumps({
        "status": status_code,
        "error": message
    })


def mqtt_to_regex( topic):
    topic = topic.replace("+", "[^/]+")
    topic = topic.replace("#", ".*")
    return "^" + topic + "$"


def _load_json_body():
    body = cherrypy.request.body.read()
    try:
        return json.loads(body)
    except Exception:
        raise cherrypy.HTTPError(400, "Invalid JSON format")