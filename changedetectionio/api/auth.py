from flask import request, make_response, jsonify
from functools import wraps


# Simple API auth key comparison
# @todo - Maybe short lived token in the future?

def check_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        datastore = args[0].datastore

        config_api_token_enabled = datastore.data['settings']['application'].get('api_access_token_enabled')
        config_api_token = datastore.data['settings']['application'].get('api_access_token')

        # config_api_token_enabled - a UI option in settings if access should obey the key or not
        if config_api_token_enabled:
            if request.headers.get('x-api-key') != config_api_token:
                return make_response(
                    jsonify("Invalid access - API key invalid."), 403
                )

        return f(*args, **kwargs)

    return decorated
