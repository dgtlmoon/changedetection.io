from collections import OrderedDict

from changedetectionio.notification import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
from changedetectionio.notification_service import (
    NotificationService,
    _get_content_notification_configs,
    watch_will_send_content_changed_notification,
)


class FakeWatch(dict):
    history = {1: 'old', 2: 'new'}


class FakeDatastore:
    def __init__(self, watch, tags, application=None):
        self.tags = tags
        self.data = {
            'settings': {
                'application': {
                    'notification_urls': [],
                    'notification_title': 'Global title',
                    'notification_body': 'Global body',
                    'notification_format': 'text',
                    **(application or {}),
                },
            },
            'watching': {watch['uuid']: watch},
        }

    def get_all_tags_for_watch(self, uuid):
        return self.tags

    def update_watch(self, uuid, update_obj):
        self.data['watching'][uuid].update(update_obj)


def _watch(**values):
    return FakeWatch({
        'uuid': 'watch-uuid',
        'notification_urls': [],
        'notification_muted': False,
        'notification_alert_count': 0,
        **values,
    })


def _two_notification_groups():
    return OrderedDict({
        'telegram-group': {
            'notification_urls': ['tgram://token/chat'],
            'notification_title': 'Telegram title',
            'notification_body': 'Telegram body',
            'notification_format': 'html',
            'notification_muted': False,
        },
        'post-group': {
            'notification_urls': ['json://example.com/hook'],
            'notification_title': 'POST title',
            'notification_body': '{"event": "changed"}',
            'notification_format': 'text',
            'notification_muted': False,
        },
    })


def test_each_notification_group_resolves_as_a_complete_config():
    watch = _watch()
    datastore = FakeDatastore(watch, _two_notification_groups())

    configs = _get_content_notification_configs(datastore, watch)

    assert configs == [
        {
            'notification_urls': ['tgram://token/chat'],
            'notification_title': 'Telegram title',
            'notification_body': 'Telegram body',
            'notification_format': 'html',
        },
        {
            'notification_urls': ['json://example.com/hook'],
            'notification_title': 'POST title',
            'notification_body': '{"event": "changed"}',
            'notification_format': 'text',
        },
    ]
    assert watch_will_send_content_changed_notification(datastore, watch)


def test_content_change_queues_every_notification_group(monkeypatch):
    watch = _watch()
    datastore = FakeDatastore(watch, _two_notification_groups())
    service = NotificationService(datastore=datastore, notification_q=None)
    queued = []
    monkeypatch.setattr(
        service,
        'queue_notification_for_watch',
        lambda n_object, watch: queued.append(dict(n_object)),
    )

    assert service.send_content_changed_notification(watch['uuid']) is True

    assert [item['notification_urls'] for item in queued] == [
        ['tgram://token/chat'],
        ['json://example.com/hook'],
    ]
    assert [item['notification_title'] for item in queued] == [
        'Telegram title',
        'POST title',
    ]
    assert [item['notification_body'] for item in queued] == [
        'Telegram body',
        '{"event": "changed"}',
    ]
    assert watch['notification_alert_count'] == 1


def test_group_fields_do_not_leak_between_notification_groups():
    watch = _watch()
    tags = _two_notification_groups()
    tags['post-group']['notification_title'] = ''
    tags['post-group']['notification_body'] = ''
    datastore = FakeDatastore(watch, tags)

    configs = _get_content_notification_configs(datastore, watch)

    assert configs[1]['notification_title'] == 'Global title'
    assert configs[1]['notification_body'] == 'Global body'


def test_muted_notification_groups_are_skipped():
    watch = _watch()
    tags = _two_notification_groups()
    tags['telegram-group']['notification_muted'] = True
    datastore = FakeDatastore(watch, tags)

    configs = _get_content_notification_configs(datastore, watch)

    assert [config['notification_urls'] for config in configs] == [
        ['json://example.com/hook'],
    ]


def test_group_system_default_format_uses_global_format():
    watch = _watch()
    tags = _two_notification_groups()
    tags['telegram-group']['notification_format'] = USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
    datastore = FakeDatastore(
        watch,
        tags,
        application={'notification_format': 'markdown'},
    )

    configs = _get_content_notification_configs(datastore, watch)

    assert configs[0]['notification_format'] == 'markdown'


def test_watch_fields_override_global_notification_fallback():
    watch = _watch(
        notification_title='Watch title',
        notification_body='Watch body',
        notification_format='html',
    )
    tags = OrderedDict({
        'ordinary-tag': {
            'notification_urls': [],
            'notification_muted': False,
        },
    })
    datastore = FakeDatastore(
        watch,
        tags,
        application={
            'notification_urls': ['mailto://user:password@example.com'],
            'notification_format': 'text',
        },
    )

    configs = _get_content_notification_configs(datastore, watch)

    assert configs == [{
        'notification_urls': ['mailto://user:password@example.com'],
        'notification_title': 'Watch title',
        'notification_body': 'Watch body',
        'notification_format': 'html',
    }]


def test_watch_notification_urls_keep_priority_over_notification_groups():
    watch = _watch(
        notification_urls=['mailto://user:password@example.com'],
        notification_title='Watch title',
        notification_body='Watch body',
        notification_format='markdown',
    )
    datastore = FakeDatastore(watch, _two_notification_groups())

    configs = _get_content_notification_configs(datastore, watch)

    assert configs == [{
        'notification_urls': ['mailto://user:password@example.com'],
        'notification_title': 'Watch title',
        'notification_body': 'Watch body',
        'notification_format': 'markdown',
    }]
