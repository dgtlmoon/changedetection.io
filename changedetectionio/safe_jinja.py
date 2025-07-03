"""
Safe Jinja2 render with max payload sizes

See https://jinja.palletsprojects.com/en/3.1.x/sandbox/#security-considerations
"""

import jinja2.sandbox
import typing as t
import os

JINJA2_MAX_RETURN_PAYLOAD_SIZE = 1024 * int(os.getenv("JINJA2_MAX_RETURN_PAYLOAD_SIZE_KB", 1024 * 10))

# This is used for notifications etc, so actually it's OK to send custom HTML such as <a href> etc, but it should limit what data is available.
# (Which also limits available functions that could be called)
def render(template_str, **args: t.Any) -> str:
    jinja2_env = jinja2.sandbox.ImmutableSandboxedEnvironment(extensions=['jinja2_time.TimeExtension'])
    output = jinja2_env.from_string(template_str).render(args)
    return output[:JINJA2_MAX_RETURN_PAYLOAD_SIZE]

def render_fully_escaped(content):
    env = jinja2.sandbox.ImmutableSandboxedEnvironment(autoescape=True)
    template = env.from_string("{{ some_html|e }}")
    return template.render(some_html=content)

