def build_watch_schema(d):
    # Base JSON schema
    schema = {
        'type': 'object',
        'properties': {},
       # 'additionalProperties': False
    }

    for k, v in d.items():
        if isinstance(v, type(None)):

            schema['properties'][k] = t = {
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
                         "type": "string"
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

    # Now expand on the default values
    # pattern

    # Can also be a string (or None by default above)
    for v in ['body', 'fetch_backend', 'notification_body', 'notification_format', 'notification_title', 'proxy', 'tag', 'title', 'url',
              'webdriver_js_execute_code']:
        schema['properties'][v]['anyOf'].append({'type': 'string'})

    schema['properties']['track_ldjson_price_data']['anyOf'].append({'type': 'boolean'})

    schema['properties']['method'] = {"type": "string",
                                      "enum": ["GET", "POST", "DELETE", "PUT"]
                                      }

    from changedetectionio.notification import valid_notification_formats

    schema['properties']['notification_format'] = {'type': 'string',
                                                   'enum': list(valid_notification_formats.keys())
                                                   }

    # Stuff that shouldnt be available but is just state-storage
    for v in ['previous_md5', 'last_error', 'has_ldjson_price_data', 'previous_md5_before_filters', 'uuid']:
        del schema['properties'][v]

    schema['properties']['webdriver_delay']['anyOf'].append({'type': 'integer'})

    # headers ? and time ? (make time reusable)
    return schema
# "enum": ["one", "two", "three"]
