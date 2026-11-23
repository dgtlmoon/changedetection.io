import hmac

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
            # Constant-time, so how long the comparison takes says nothing about how much of the key matched
            given_api_token = request.headers.get('x-api-key')
            if given_api_token is None or config_api_token is None:
                key_matches = given_api_token == config_api_token
            else:
                key_matches = hmac.compare_digest(str(given_api_token).encode('utf-8'), str(config_api_token).encode('utf-8'))
            if not key_matches:
                return make_response(
                    jsonify("Invalid access - API key invalid."), 403
                )

        return f(*args, **kwargs)

    return decorated
