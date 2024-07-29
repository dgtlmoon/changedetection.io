import json

def fromjson(value):
    if value is None or not value:
        return ""
    return json.loads(value)
