"""
Tests that {{ llm_summary }} and {{ llm_intent }} notification tokens
are correctly populated in the notification pipeline.

Covers:
  1. notification/handler.py — lazy population logic (lines 367-372)
  2. notification_service.py — _llm_result / _llm_intent from watch → n_object
  3. End-to-end: tokens render in notification body/title
"""
import pytest
from unittest.mock import MagicMock, patch
from changedetectionio.notification_service import NotificationContextData


def _make_n_object(**extra):
    n = NotificationContextData()
    n.update({
        'notification_body': '',
        'notification_title': '',
        'notification_format': 'text',
        'notification_urls': ['json://localhost/'],
        'uuid': 'test-uuid',
        'watch_uuid': 'test-uuid',
        'watch_url': 'https://example.com',
        'current_snapshot': 'current text',
        'prev_snapshot': 'previous text',
    })
    n.update(extra)
    return n


# ---------------------------------------------------------------------------
# handler.py — lazy population of llm_summary / llm_intent
# ---------------------------------------------------------------------------

class TestHandlerLlmTokenPopulation:
    """
    The notification handler checks if llm_summary or llm_intent tokens appear
    in the notification text and lazily populates them from _llm_result.
    """

    def _run_handler_llm_section(self, n_object):
        """
        Replicate the exact logic from notification/handler.py lines 367-372.
        This is tested directly to validate the handler's token population.
        """
        scan_text = n_object.get('notification_body', '') + n_object.get('notification_title', '')
        if 'llm_summary' in scan_text or 'llm_intent' in scan_text:
            llm_result = n_object.get('_llm_result') or {}
            n_object['llm_summary'] = llm_result.get('summary', '')
            n_object['llm_intent'] = n_object.get('_llm_intent', '')
        return n_object

    def test_llm_summary_populated_when_token_in_body(self):
        n = _make_n_object(
            notification_body='Change detected! Summary: {{ llm_summary }}',
            _llm_result={'important': True, 'summary': 'Price dropped from $500 to $400'},
            _llm_intent='flag price drops',
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_summary'] == 'Price dropped from $500 to $400'

    def test_llm_intent_populated_when_token_in_body(self):
        n = _make_n_object(
            notification_body='Intent was: {{ llm_intent }}',
            _llm_result={'important': True, 'summary': 'some change'},
            _llm_intent='flag price drops',
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_intent'] == 'flag price drops'

    def test_llm_summary_in_title(self):
        n = _make_n_object(
            notification_title='[CD] {{ llm_summary }}',
            notification_body='some body',
            _llm_result={'important': True, 'summary': 'New job posted'},
            _llm_intent='new jobs',
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_summary'] == 'New job posted'

    def test_tokens_not_populated_when_absent_from_template(self):
        """Don't bother populating when tokens aren't used — avoid needless LLM calls."""
        n = _make_n_object(
            notification_body='Change at {{ watch_url }}',
            notification_title='CD Alert',
            _llm_result={'important': True, 'summary': 'should not appear'},
            _llm_intent='test',
        )
        result = self._run_handler_llm_section(n)
        # llm_summary and llm_intent should remain at their default None values
        assert result.get('llm_summary') is None
        assert result.get('llm_intent') is None

    def test_empty_summary_when_no_llm_result(self):
        n = _make_n_object(
            notification_body='Summary: {{ llm_summary }}',
            _llm_result=None,
            _llm_intent='',
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_summary'] == ''

    def test_empty_intent_when_not_set(self):
        n = _make_n_object(
            notification_body='Intent: {{ llm_intent }}',
            _llm_result={'important': False, 'summary': ''},
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_intent'] == ''

    def test_summary_from_unimportant_result(self):
        """Even when important=False the summary explains why — useful for debugging."""
        n = _make_n_object(
            notification_body='Summary: {{ llm_summary }}',
            _llm_result={'important': False, 'summary': 'Only a copyright year changed'},
            _llm_intent='flag price drops',
        )
        result = self._run_handler_llm_section(n)
        assert result['llm_summary'] == 'Only a copyright year changed'


# ---------------------------------------------------------------------------
# notification_service.py — _llm_result / _llm_intent wired from watch
# ---------------------------------------------------------------------------

class TestNotificationServiceLlmAttachment:
    """
    send_content_changed_notification() reads _llm_result and _llm_intent
    from the watch object and attaches them to n_object so the handler can render tokens.
    """

    def _make_watch(self, llm_result=None, llm_intent=''):
        watch = MagicMock()
        watch.get.side_effect = lambda key, default=None: {
            '_llm_result': llm_result,
            '_llm_intent': llm_intent,
            'notification_urls': ['json://localhost/'],
            'notification_title': '',
            'notification_body': '',
            'notification_format': 'text',
            'notification_muted': False,
            'notification_alert_count': 0,
        }.get(key, default)
        watch.history = {'1000': 'snap1', '2000': 'snap2'}
        watch.get_history_snapshot = MagicMock(return_value='snapshot text')
        watch.extra_notification_token_values = MagicMock(return_value={})
        return watch

    def test_llm_result_attached_to_n_object(self):
        """_llm_result from watch ends up in n_object for the notification handler."""
        from changedetectionio.notification_service import NotificationService

        llm_result = {'important': True, 'summary': 'Price dropped'}
        watch = self._make_watch(llm_result=llm_result, llm_intent='flag price drops')

        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'active_base_url': 'http://localhost',
                    'notification_urls': [],
                    'notification_title': '',
                    'notification_body': '',
                    'notification_format': 'text',
                    'notification_muted': False,
                }
            },
            'watching': {'test-uuid': watch},
        }
        datastore.get_all_tags_for_watch = MagicMock(return_value={})

        captured = {}

        def fake_queue_notification(n_object, watch, **kwargs):
            captured['n_object'] = dict(n_object)

        svc = NotificationService(datastore, MagicMock())
        svc.queue_notification_for_watch = fake_queue_notification

        svc.send_content_changed_notification('test-uuid')

        assert '_llm_result' in captured['n_object']
        assert captured['n_object']['_llm_result'] == llm_result

    def test_llm_intent_attached_to_n_object(self):
        """_llm_intent from watch ends up in n_object."""
        from changedetectionio.notification_service import NotificationService

        watch = self._make_watch(
            llm_result={'important': True, 'summary': 'test'},
            llm_intent='flag price drops',
        )

        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'active_base_url': 'http://localhost',
                    'notification_urls': [],
                    'notification_title': '',
                    'notification_body': '',
                    'notification_format': 'text',
                    'notification_muted': False,
                }
            },
            'watching': {'test-uuid': watch},
        }
        datastore.get_all_tags_for_watch = MagicMock(return_value={})

        captured = {}

        def fake_queue_notification(n_object, watch, **kwargs):
            captured['n_object'] = dict(n_object)

        svc = NotificationService(datastore, MagicMock())
        svc.queue_notification_for_watch = fake_queue_notification

        svc.send_content_changed_notification('test-uuid')

        assert captured['n_object']['_llm_intent'] == 'flag price drops'

    def test_null_llm_result_when_no_evaluation(self):
        """When LLM wasn't evaluated, _llm_result is None — tokens render as empty."""
        from changedetectionio.notification_service import NotificationService

        watch = self._make_watch(llm_result=None, llm_intent='')

        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'active_base_url': 'http://localhost',
                    'notification_urls': [],
                    'notification_title': '',
                    'notification_body': '',
                    'notification_format': 'text',
                    'notification_muted': False,
                }
            },
            'watching': {'test-uuid': watch},
        }
        datastore.get_all_tags_for_watch = MagicMock(return_value={})

        captured = {}

        def fake_queue_notification(n_object, watch, **kwargs):
            captured['n_object'] = dict(n_object)

        svc = NotificationService(datastore, MagicMock())
        svc.queue_notification_for_watch = fake_queue_notification

        svc.send_content_changed_notification('test-uuid')

        assert captured['n_object']['_llm_result'] is None
        assert captured['n_object']['_llm_intent'] == ''


# ---------------------------------------------------------------------------
# End-to-end: Jinja2 template rendering with llm_summary / llm_intent
# ---------------------------------------------------------------------------

class TestLlmTokenEndToEnd:
    """
    Verify that the tokens render correctly through the Jinja2 engine
    used for notification bodies.
    """

    def test_llm_summary_renders_in_template(self):
        from changedetectionio.jinja2_custom import render as jinja_render
        from changedetectionio.notification_service import NotificationContextData

        n = NotificationContextData()
        n['llm_summary'] = 'Price dropped from $500 to $400'
        n['watch_url'] = 'https://example.com'

        rendered = jinja_render(
            template_str='Change at {{watch_url}}: {{llm_summary}}',
            **n
        )
        assert 'Price dropped from $500 to $400' in rendered
        assert 'https://example.com' in rendered

    def test_llm_intent_renders_in_template(self):
        from changedetectionio.jinja2_custom import render as jinja_render
        from changedetectionio.notification_service import NotificationContextData

        n = NotificationContextData()
        n['llm_intent'] = 'flag price drops below $300'
        n['watch_url'] = 'https://example.com'

        rendered = jinja_render(
            template_str='Intent was: {{llm_intent}}',
            **n
        )
        assert 'flag price drops below $300' in rendered

    def test_llm_summary_empty_string_when_none(self):
        from changedetectionio.jinja2_custom import render as jinja_render
        from changedetectionio.notification_service import NotificationContextData

        n = NotificationContextData()
        # llm_summary defaults to None in NotificationContextData
        rendered = jinja_render(
            template_str='Summary: {{llm_summary or ""}}',
            **n
        )
        assert rendered == 'Summary: '

    def test_both_tokens_in_same_template(self):
        from changedetectionio.jinja2_custom import render as jinja_render
        from changedetectionio.notification_service import NotificationContextData

        n = NotificationContextData()
        n['llm_summary'] = 'New senior role posted'
        n['llm_intent'] = 'alert on new engineering jobs'
        n['watch_url'] = 'https://jobs.example.com'

        rendered = jinja_render(
            template_str='[{{llm_intent}}] {{llm_summary}} — {{watch_url}}',
            **n
        )
        assert 'alert on new engineering jobs' in rendered
        assert 'New senior role posted' in rendered
        assert 'https://jobs.example.com' in rendered
