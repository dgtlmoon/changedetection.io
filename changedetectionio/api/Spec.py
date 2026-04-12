import functools
from flask import make_response
from flask_restful import Resource


@functools.cache
def _get_spec_yaml():
    """Build and cache the merged spec as a YAML string (only serialized once per process)."""
    import yaml
    from changedetectionio.api import build_merged_spec_dict
    return yaml.dump(build_merged_spec_dict(), default_flow_style=False, allow_unicode=True)


class Spec(Resource):
    def get(self):
        """Return the merged OpenAPI spec including all registered processor extensions."""
        return make_response(
            _get_spec_yaml(),
            200,
            {'Content-Type': 'application/yaml'}
        )
