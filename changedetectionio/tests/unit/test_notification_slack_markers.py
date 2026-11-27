#!/usr/bin/env python3
"""Slack renders neither HTML nor colours: changed lines are marked with a coloured emoji and a word,
whatever the notification format, and a JSON body posted straight to a Slack webhook stays valid JSON."""
import json

import pytest

from changedetectionio.diff import (
    ADDED_PLACEMARKER_CLOSED, ADDED_PLACEMARKER_OPEN, CHANGED_INTO_PLACEMARKER_CLOSED,
    CHANGED_INTO_PLACEMARKER_OPEN, CHANGED_PLACEMARKER_CLOSED, CHANGED_PLACEMARKER_OPEN,
    REMOVED_PLACEMARKER_CLOSED, REMOVED_PLACEMARKER_OPEN,
)
from changedetectionio.notification.handler import (
    SLACK_ADDED_MARK, SLACK_CHANGED_MARK, SLACK_REMOVED_MARK, is_slack_url, replace_placemarkers_in_text,
)

DIFF = '\n'.join([
    f'{REMOVED_PLACEMARKER_OPEN}old line{REMOVED_PLACEMARKER_CLOSED}',
    f'{ADDED_PLACEMARKER_OPEN}new line{ADDED_PLACEMARKER_CLOSED}',
    f'{CHANGED_PLACEMARKER_OPEN}price 349{CHANGED_PLACEMARKER_CLOSED}',
    f'{CHANGED_INTO_PLACEMARKER_OPEN}price 279{CHANGED_INTO_PLACEMARKER_CLOSED}',
])

EXPECTED = '\n'.join([
    f'{SLACK_REMOVED_MARK} (removed) old line',
    f'{SLACK_ADDED_MARK} (added) new line',
    f'{SLACK_CHANGED_MARK} (changed) price 349',
    f'{SLACK_ADDED_MARK} (into) price 279',
])


@pytest.mark.parametrize('url', [
    'slack://TOKEN_A/TOKEN_B/TOKEN_C',
    'slack://BOT_TOKEN/#website-changes',
    'https://hooks.slack.com/services/TOKEN_A/TOKEN_B/TOKEN_C',
    'posts://hooks.slack.com/services/TOKEN_A/TOKEN_B/TOKEN_C',
    'SLACK://TOKEN_A/TOKEN_B/TOKEN_C',
])
@pytest.mark.parametrize('output_format', ['text', 'html', 'htmlcolor', 'markdown'])
def test_slack_markers_for_every_format(url, output_format):
    assert is_slack_url(url)
    assert replace_placemarkers_in_text(DIFF, url, output_format) == EXPECTED


def test_json_body_for_slack_webhook_stays_valid():
    # What `{"text": {{ diff|tojson }} }` renders to, before the placemarkers are replaced
    body = '{"text": %s }' % json.dumps(DIFF)
    out = replace_placemarkers_in_text(body, 'posts://hooks.slack.com/services/T0/B0/x', 'htmlcolor')
    assert json.loads(out)['text'] == EXPECTED


@pytest.mark.parametrize('url', ['mailto://user:pass@example.com', 'json://example.com/slack', 'discord://id/token', ''])
def test_other_services_unchanged(url):
    assert not is_slack_url(url)
    assert SLACK_REMOVED_MARK not in replace_placemarkers_in_text(DIFF, url, 'text')
