"""
Notification Profile Type plugin registry.

NotificationProfileType is the abstract base — the only contract is send().
Plugins are free to use any delivery mechanism (Apprise, direct HTTP, SDK, etc.).

Built-in: AppriseProfileType (raw Apprise URL list).

Third-party plugins register additional types:

    from changedetectionio.notification_profiles.registry import registry, NotificationProfileType

    @registry.register
    class MyProfileType(NotificationProfileType):
        type_id      = "mytype"
        display_name = "My Service"
        icon         = "bell"
        template     = "my_plugin/notification_profiles/types/mytype.html"

        def send(self, config: dict, n_object: dict, datastore) -> bool:
            requests.post(config['webhook_url'], json={"text": n_object['notification_body']})
            return True
"""

from abc import ABC, abstractmethod


class NotificationProfileType(ABC):
    type_id:      str = NotImplemented
    display_name: str = NotImplemented
    icon:         str = "bell"          # feather icon name
    template:     str = NotImplemented  # Jinja2 partial rendered in the profile edit form

    @abstractmethod
    def send(self, config: dict, n_object: dict, datastore) -> bool:
        """
        Deliver the notification.

        Args:
            config:    The profile's config dict (type-specific fields).
            n_object:  Fully-rendered NotificationContextData (title, body, format, etc.).
            datastore: App datastore for any extra lookups.

        Returns True on success, False on failure (do not raise — log instead).
        """

    def validate(self, config: dict) -> None:
        """Raise ValueError with a user-readable message on invalid config."""
        pass

    def get_url_hint(self, config: dict) -> str:
        """Short display string shown in the selector chip tooltip / dropdown row."""
        return ''


class AppriseProfileType(NotificationProfileType):
    """Delivers notifications via Apprise using a raw URL list."""

    type_id      = "apprise"
    display_name = "Apprise"
    icon         = "bell"
    template     = "notification_profiles/types/apprise.html"

    def get_apprise_urls(self, config: dict) -> list:
        return config.get('notification_urls') or []

    def send(self, config: dict, n_object, datastore) -> bool:
        from changedetectionio.notification.handler import process_notification
        from changedetectionio.notification_service import NotificationContextData
        urls = self.get_apprise_urls(config)
        if not urls:
            return False
        if not isinstance(n_object, NotificationContextData):
            n_object = NotificationContextData(n_object)
        n_object['notification_urls']   = urls
        n_object['notification_title']  = config.get('notification_title') or n_object.get('notification_title')
        n_object['notification_body']   = config.get('notification_body')  or n_object.get('notification_body')
        n_object['notification_format'] = config.get('notification_format') or n_object.get('notification_format')
        process_notification(n_object, datastore)
        return True

    def get_url_hint(self, config: dict) -> str:
        urls = config.get('notification_urls') or []
        if urls:
            u = urls[0]
            return (u[:60] + '…') if len(u) > 60 else u
        return ''


class _Registry:
    def __init__(self):
        self._types: dict = {}

    def register(self, cls):
        """Register a NotificationProfileType subclass. Usable as a decorator."""
        instance = cls()
        self._types[instance.type_id] = instance
        return cls

    def get(self, type_id: str) -> NotificationProfileType:
        return self._types.get(type_id, self._types.get('apprise'))

    def all(self) -> list:
        return list(self._types.values())

    def choices(self) -> list:
        return [(t.type_id, t.display_name) for t in self._types.values()]


registry = _Registry()
registry.register(AppriseProfileType)
