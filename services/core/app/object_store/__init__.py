"""Object-storage adapter.

Two implementations; one is picked at startup from
``settings.object_store_backend``:

* ``local``  — :class:`LocalObjectStore`. Filesystem-backed. Dev + tests.
* ``s3``     — :class:`S3ObjectStore`. aioboto3-backed. Production.

Callers never construct either directly in production code — they call
:func:`build_object_store` which returns the configured impl.
"""

from .factory import build_object_store
from .local import LocalObjectStore
from .protocol import InvalidObjectKey, ObjectNotFound, ObjectStore

# ``S3ObjectStore`` is imported lazily from factory.build_object_store
# so test environments without ``aioboto3`` installed can still import
# this package.

__all__ = [
    "InvalidObjectKey",
    "LocalObjectStore",
    "ObjectNotFound",
    "ObjectStore",
    "build_object_store",
]
