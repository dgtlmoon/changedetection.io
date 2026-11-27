"""
Read-only, shared ("interned") copies of watch values that are identical across most watches.

At 84,756 real watches, `time_schedule_limit` was 305 MiB of the 651 MiB held by watch dicts,
and not one of them had a schedule enabled - every watch held its own private copy of the same
15 nested dicts. Interning collapses identical values to a single object.

Sharing one object between watches is only safe if nobody can write to it, otherwise one write
would change every watch at once. FrozenDict blocks every Python-level write and raises instead,
so a missed in-place mutation fails loudly on that call rather than silently corrupting other
watches.

FrozenDict is a real dict subclass, so json/orjson/Flask jsonify/Jinja tojson, isinstance(x, dict),
== against plain dicts and WTForms population all keep working unchanged. (A msgspec Struct was
considered, but json.dumps(watch) in the share feature and the API GET response would both raise.)

To change an interned value, modify a thaw()'d copy and assign it back:
    schedule = thaw(watch['time_schedule_limit'])
    schedule['monday']['enabled'] = False
    watch['time_schedule_limit'] = schedule
"""
import weakref

import orjson

# Keys whose values are interned when set on a watch_base. Only add a key after confirming
# nothing mutates its value in place (grep for watch['key'][...] = / .update( / .append( etc.)
INTERNED_WATCH_KEYS = ('time_schedule_limit',)


class FrozenDict(dict):
    __slots__ = ('__weakref__',)

    def _read_only(self, *args, **kwargs):
        raise TypeError(f"{type(self).__name__} is read-only and may be shared between watches, "
                        f"assign a new value instead of modifying it in place")

    __setitem__ = __delitem__ = __ior__ = _read_only
    update = setdefault = pop = popitem = clear = _read_only

    # Immutable, so copies can be the same object - this is what keeps clone()/deepcopy()/
    # _get_commit_data() from turning the shared object back into private copies
    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        # The default pickle protocol rebuilds via __setitem__, which is blocked
        return (FrozenDict, (dict(self),))


def thaw(value):
    """Deep, writable plain-dict/list copy of an interned value, to modify and assign back."""
    if isinstance(value, dict):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def _freeze(value):
    if isinstance(value, dict):
        return FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


# Weak values: a value is dropped from the pool once no watch holds it any more
_pool = weakref.WeakValueDictionary()


def intern_frozen(value):
    """
    Return the shared read-only copy of a dict value, creating it on first sight.

    The pool key is the exact orjson serialisation, so key order and value types are part of
    identity ({"enabled": 1} and {"enabled": true} stay distinct). The interned copy always
    serialises byte-identically to the value it replaced, so watch.json is unchanged on disk.

    Anything that isn't a plain dict, or can't be serialised, is returned unchanged.
    """
    if type(value) is not dict:
        return value
    try:
        key = orjson.dumps(value)
    except (TypeError, orjson.JSONEncodeError):
        return value

    frozen = _pool.get(key)
    if frozen is None:
        frozen = _freeze(value)
        _pool[key] = frozen
    return frozen
