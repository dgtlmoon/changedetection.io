"""
Notification Profile Type plugin registry.

NotificationProfileType is the abstract base — the only contract is send().
Plugins are free to use any delivery mechanism (Apprise, direct HTTP, SDK, etc.).

Built-in: AppriseProfileType (raw Apprise URL list).

Third-party plugins register additional types:

    from changedetectionio.notification_profiles.registry import registry, NotificationProfileType

    @registry.register
    class MyProfileType(NotificationProfileType):
        type_id             = "mytype"
        display_name        = "My Service"
        icon                = "bell"
        template            = "my_plugin/notification_profiles/types/mytype.html"
        # Optional: declare a WTForms Form class to expose type-wide system defaults in the UI
        # defaults_form_class = MyDefaultsForm
        # defaults_template   = "my_plugin/notification_profiles/type_defaults/mytype.html"

        def send(self, config: dict, n_object: dict, datastore) -> bool:
            # Use self.get_type_defaults(datastore) to read system-wide defaults
            # Use self.resolve(profile_val, system_val, hardcoded_val) for the cascade
            system_defaults = self.get_type_defaults(datastore)
            body = self.resolve(config.get('body'), system_defaults.get('body'), 'Default body')
            requests.post(config['webhook_url'], json={"text": body})
            return True
"""

from abc import ABC, abstractmethod


class NotificationProfileType(ABC):
    type_id:            str  = NotImplemented
    display_name:       str  = NotImplemented
    icon:               str  = "bell"   # feather icon name
    template:           str  = NotImplemented  # Jinja2 partial rendered in the profile edit form
    defaults_form_class: type = None    # WTForms Form subclass for type-specific system-wide defaults (None = no defaults UI)
    defaults_template:  str  = None    # Optional Jinja2 template for defaults form (falls back to generic)

    def get_type_defaults(self, datastore) -> dict:
        """Read this type's system-wide configurable defaults from the datastore."""
        return (
            datastore.data['settings']['application']
            .setdefault('notification_type_defaults', {})
            .get(self.type_id, {})
        )

    @staticmethod
    def resolve(profile_val, system_val, hardcoded_val):
        """3-tier cascade: profile config → type system defaults → hardcoded constant."""
        return profile_val or system_val or hardcoded_val

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

    type_id             = "apprise"
    display_name        = "Apprise"
    icon                = "bell"
    template            = "notification_profiles/types/apprise.html"
    defaults_template   = "notification_profiles/type_defaults/apprise.html"

    @property
    def defaults_form_class(self):
        # Imported here to avoid circular imports at module load time
        from changedetectionio.blueprint.notification_profiles.forms import AppriseDefaultsForm
        return AppriseDefaultsForm

    def get_apprise_urls(self, config: dict) -> list:
        return config.get('notification_urls') or []

    def send(self, config: dict, n_object, datastore) -> bool:
        from changedetectionio.notification.handler import process_notification
        from changedetectionio.notification_service import NotificationContextData
        from changedetectionio.notification import (
            default_notification_body,
            default_notification_format,
            default_notification_title,
        )
        urls = self.get_apprise_urls(config)
        if not urls:
            return False
        if not isinstance(n_object, NotificationContextData):
            n_object = NotificationContextData(n_object)

        system_defaults = self.get_type_defaults(datastore)

        # 4-tier cascade: profile config → type system defaults → pre-set n_object value → hardcoded constants
        # n_object may carry a specific alert title/body (e.g. filter-failure, browser-step-failure)
        # that is more meaningful than the generic hardcoded default — preserve it as the penultimate fallback.
        n_object['notification_urls']   = urls
        n_object['notification_title']  = self.resolve(
            config.get('notification_title'),
            system_defaults.get('notification_title'),
            n_object.get('notification_title') or default_notification_title,
        )
        n_object['notification_body']   = self.resolve(
            config.get('notification_body'),
            system_defaults.get('notification_body'),
            n_object.get('notification_body') or default_notification_body,
        )
        n_object['notification_format'] = self.resolve(
            config.get('notification_format'),
            system_defaults.get('notification_format'),
            n_object.get('notification_format') or default_notification_format,
        )
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
