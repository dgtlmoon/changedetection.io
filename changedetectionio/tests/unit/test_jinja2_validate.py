#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m pytest changedetectionio/tests/unit/test_jinja2_validate.py

from changedetectionio.jinja2_custom.validate import validate_jinja2_fields


def test_valid_and_non_template_values_pass():
    assert validate_jinja2_fields(
        url="https://example.com/{{ 1+1 }}",
        link_to_open="https://example.com/{% if true %}yes{% endif %}",
        body='{"q": "{%22key%22:1}"}',   # URL-encoded JSON, not Jinja2
        headers={'x-plain': 'value', 'x-templated': '{{ 2*2 }}'},
    ) == {}
    assert validate_jinja2_fields() == {}


def test_broken_templates_are_reported_per_field():
    errors = validate_jinja2_fields(
        url="https://example.com/{{ broken(",
        link_to_open="https://example.com/{% if %}",
        body="{{ unclosed",
        headers={'x-ok': 'fine', 'x-bad': '{% endfor %}'},
    )
    assert set(errors) == {'url', 'link_to_open', 'body', 'headers'}
    assert errors['body'].startswith('Invalid template syntax')
    # The broken header is named so the user knows which one to fix
    assert '"x-bad"' in errors['headers']


def test_non_string_values_are_ignored():
    assert validate_jinja2_fields(url=None, body=None, headers={'x-num': 5}) == {}
