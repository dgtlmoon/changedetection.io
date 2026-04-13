"""S3 / S3-compatible object store (AWS S3, Cloudflare R2, MinIO).

Uses ``aioboto3`` — an async wrapper over ``boto3`` that speaks the
same API. Any S3-compatible backend works; pass the custom endpoint
URL via ``endpoint_url``.

Credentials follow the normal AWS resolution chain (env vars, EC2 /
task role, shared credentials file). In production we set IAM
policies that restrict the credential to a bucket prefix, so even a
code bug cannot reach another tenant's blobs.

``aioboto3`` is imported lazily so the rest of the service can run
without it installed — useful for dev + CI where LocalObjectStore is
the default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .protocol import ObjectNotFound, validate_key

if TYPE_CHECKING:
    import aioboto3


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        # Import at construction time so dev envs without aioboto3
        # installed don't crash on package import.
        import aioboto3  # noqa: F401 — used via the session below

        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key

    def _session(self) -> "aioboto3.Session":
        import aioboto3

        return aioboto3.Session(
            aws_access_key_id=self._aws_access_key_id,
            aws_secret_access_key=self._aws_secret_access_key,
            region_name=self._region,
        )

    def _client(self):
        return self._session().client("s3", endpoint_url=self._endpoint_url)

    async def put(self, key: str, body: bytes, *, content_type: str) -> None:
        validate_key(key)
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

    async def get(self, key: str) -> bytes:
        validate_key(key)
        async with self._client() as s3:
            try:
                resp = await s3.get_object(Bucket=self._bucket, Key=key)
            except s3.exceptions.NoSuchKey as exc:
                raise ObjectNotFound(key) from exc
            return await resp["Body"].read()

    async def delete(self, key: str) -> None:
        validate_key(key)
        async with self._client() as s3:
            # S3's DeleteObject is idempotent — it doesn't 404 on
            # missing keys. For parity with LocalObjectStore we HEAD
            # first so we can raise ObjectNotFound on absence.
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception as exc:  # noqa: BLE001
                raise ObjectNotFound(key) from exc
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        validate_key(key)
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
            except Exception:  # noqa: BLE001
                return False
            return True

    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        validate_key(key)
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
