"""
Base class for small, immutable (frozen) pydantic dataclasses that hang off a Watch/Tag.

Any field whose value equals its declared default is swapped for that one default
instance, recursively, so the default is held once per process instead of once per watch.
With 40,000 watches a plain nested dict of defaults (e.g. the 7-day time_schedule_limit,
~3.7KiB each) costs ~150MB; shared, it costs nothing.

On disk the same rule applies via to_storage() (exclude_defaults), so watch.json only
holds what differs from the default and loads straight back onto the shared instances.

Subclasses must be declared with @pydantic.dataclasses.dataclass(slots=True, frozen=True),
frozen is what makes sharing safe - nothing can mutate the shared default in place,
replace the value instead.
"""
import dataclasses
from typing import ClassVar

from pydantic import TypeAdapter, model_validator


class DefaultShared:
    __slots__ = ()

    # Opt-in per model: treat None/blank values as "use this field's default" instead of failing
    # validation. Stops one empty field in an old watch.json (or form post) from throwing away the
    # whole structure. Off by default because for some fields '' may be a deliberate value.
    BLANK_MEANS_DEFAULT: ClassVar[bool] = False

    @model_validator(mode='before')
    @classmethod
    def _blank_means_default(cls, data):
        if cls.BLANK_MEANS_DEFAULT and isinstance(data, dict):
            return {k: v for k, v in data.items()
                    if not (v is None or (isinstance(v, str) and not v.strip()))}
        return data

    @model_validator(mode='after')
    def _share_defaults(self):
        # Pydantic validates bottom-up, so nested values are already canonical by the
        # time the parent compares them, which makes the == below cheap (identity first)
        for f in dataclasses.fields(self):
            if f.default is dataclasses.MISSING:
                continue
            value = getattr(self, f.name)
            if value is not f.default and value == f.default:
                object.__setattr__(self, f.name, f.default)
        return self

    # Immutable, so copies can share the same instance (Watch objects are deepcopied on every check)
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    @classmethod
    def _adapter(cls):
        adapter = cls.__dict__.get('_type_adapter')
        if adapter is None:
            adapter = TypeAdapter(cls)
            type.__setattr__(cls, '_type_adapter', adapter)
        return adapter

    @classmethod
    def validate(cls, value):
        """dict (from watch.json, the form or the API) -> instance"""
        if isinstance(value, cls):
            return value
        return cls._adapter().validate_python(value)

    def to_storage(self):
        """Only what differs from the defaults, for watch.json"""
        return self._adapter().dump_python(self, mode='json', exclude_defaults=True)

    def to_api(self):
        """The full structure for API responses, unset (None) values are left out so a GET can be PUT straight back"""
        return self._adapter().dump_python(self, mode='json', exclude_none=True)
