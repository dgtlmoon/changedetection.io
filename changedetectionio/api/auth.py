from flask import request, make_response, jsonify
from functools import wraps


# Simple API auth key comparison
# @todo - Maybe short lived token in the future?

def check_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        datastore = args[0].datastore

        config_api_token_enabled = datastore.data['settings']['application'].get('api_access_token_enabled')
        if not config_api_token_enabled:
            return

        try:
            api_key_header = request.headers['x-api-key']
        except KeyError:
            return make_response(
                jsonify("No authorization x-api-key header."), 403
            )

        config_api_token = datastore.data['settings']['application'].get('api_access_token')

        if api_key_header != config_api_token:
            return make_response(
                jsonify("Invalid access - API key invalid."), 403
            )

        return f(*args, **kwargs)

    return decorated
