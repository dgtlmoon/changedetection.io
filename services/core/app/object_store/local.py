"""Filesystem-backed object store. Dev + tests only.

Writes blobs to ``{root}/{key}``. Key validation (see
``protocol.validate_key``) already rejects traversal attempts so an
attacker-controlled key can't escape ``root``; we additionally
re-resolve the final path and refuse anything that, after
``pathlib.Path.resolve()``, is outside ``root``.

Presigned URLs aren't really meaningful locally — we return a
``file://`` URL so tests that assert on the shape still pass.
"""

from __future__ import annotations

from pathlib import Path

from .protocol import InvalidObjectKey, ObjectNotFound, validate_key


class LocalObjectStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        validate_key(key)
        p = (self._root / key).resolve()
        try:
            p.relative_to(self._root)
        except ValueError as exc:
            # Defence in depth — validate_key already blocked ``..``.
            raise InvalidObjectKey(key) from exc
        return p

    async def put(self, key: str, body: bytes, *, content_type: str) -> None:
        del content_type  # not retained locally; S3 keeps it as metadata
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp + rename.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        path.unlink()

    async def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except InvalidObjectKey:
            return False

    async def presigned_url(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return self._resolve(key).as_uri()
