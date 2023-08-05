# Responsible for building the storage dict into a set of rules ("JSON Schema") acceptable via the API
# Probably other ways to solve this when the backend switches to some ORM

def build_time_between_check_json_schema():
    # Setup time between check schema
    schema_properties_time_between_check = {
        "type": "object",
        "additionalProperties": False,
        "properties": {}
    }
    for p in ['weeks', 'days', 'hours', 'minutes', 'seconds']:
        schema_properties_time_between_check['properties'][p] = {
            "anyOf": [
                {
                    "type": "integer"
                },
                {
                    "type": "null"
                }
            ]
        }

    return schema_properties_time_between_check

def build_watch_json_schema(d):
    # Base JSON schema
    schema = {
        'type': 'object',
        'properties': {},
    }

    for k, v in d.items():
        # @todo 'integer' is not covered here because its almost always for internal usage

        if isinstance(v, type(None)):
            schema['properties'][k] = {
                "anyOf": [
                    {"type": "null"},
                ]
            }
        elif isinstance(v, list):
            schema['properties'][k] = {
                "anyOf": [
                    {"type": "array",
                     # Always is an array of strings, like text or regex or something
                     "items": {
                         "type": "string",
                         "maxLength": 5000
                     }
                     },
                ]
            }
        elif isinstance(v, bool):
            schema['properties'][k] = {
                "anyOf": [
                    {"type": "boolean"},
                ]
            }
        elif isinstance(v, str):
            schema['properties'][k] = {
                "anyOf": [
                    {"type": "string",
                     "maxLength": 5000},
                ]
            }

    # Can also be a string (or None by default above)
    for v in ['body',
              'notification_body',
              'notification_format',
              'notification_title',
              'proxy',
              'tag',
              'title',
              'webdriver_js_execute_code'
              ]:
        schema['properties'][v]['anyOf'].append({'type': 'string', "maxLength": 5000})

    # None or Boolean
    schema['properties']['track_ldjson_price_data']['anyOf'].append({'type': 'boolean'})

    schema['properties']['method'] = {"type": "string",
                                      "enum": ["GET", "POST", "DELETE", "PUT"]
                                      }

    schema['properties']['fetch_backend']['anyOf'].append({"type": "string",
                                                           "enum": ["html_requests", "html_webdriver"]
                                                           })



    # All headers must be key/value type dict
    schema['properties']['headers'] = {
        "type": "object",
        "patternProperties": {
            # Should always be a string:string type value
            ".*": {"type": "string"},
        }
    }

    from changedetectionio.notification import valid_notification_formats

    schema['properties']['notification_format'] = {'type': 'string',
                                                   'enum': list(valid_notification_formats.keys())
                                                   }

    # Stuff that shouldn't be available but is just state-storage
    for v in ['previous_md5', 'last_error', 'has_ldjson_price_data', 'previous_md5_before_filters', 'uuid']:
        del schema['properties'][v]

    schema['properties']['webdriver_delay']['anyOf'].append({'type': 'integer'})

    schema['properties']['time_between_check'] = build_time_between_check_json_schema()

    # headers ?
    return schema

