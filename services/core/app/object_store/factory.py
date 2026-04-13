"""Object-store backend factory."""

from __future__ import annotations

from ..config import get_settings
from .local import LocalObjectStore
from .protocol import ObjectStore


def build_object_store() -> ObjectStore:
    """Return the configured :class:`ObjectStore` singleton.

    Picked from ``settings.object_store_backend``:

    * ``local`` — ``LocalObjectStore(settings.object_store_local_root)``.
    * ``s3``    — ``S3ObjectStore(...)``.

    The S3 path imports ``aioboto3`` on demand so dev environments
    without it installed still work.
    """
    settings = get_settings()
    backend = settings.object_store_backend

    if backend == "local":
        return LocalObjectStore(settings.object_store_local_root)

    if backend == "s3":
        from .s3 import S3ObjectStore

        if not settings.object_store_s3_bucket:
            raise RuntimeError(
                "CORE_OBJECT_STORE_S3_BUCKET is required when "
                "object_store_backend=s3"
            )
        return S3ObjectStore(
            bucket=settings.object_store_s3_bucket,
            region=settings.object_store_s3_region,
            endpoint_url=settings.object_store_s3_endpoint_url,
            aws_access_key_id=settings.object_store_s3_access_key_id,
            aws_secret_access_key=settings.object_store_s3_secret_access_key,
        )

    raise RuntimeError(f"unknown object_store_backend: {backend!r}")
