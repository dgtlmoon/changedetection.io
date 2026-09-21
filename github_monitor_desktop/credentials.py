from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes


class CredentialError(RuntimeError):
    pass


_DESCRIPTION = "GitHub Monitor Desktop token"
_ENTROPY = b"changedetection.io-github-monitor-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(value: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _require_windows() -> None:
    if sys.platform != "win32":
        raise CredentialError("令牌持久化仅支持 Windows DPAPI。")


def protect_token(token: str) -> str:
    """Encrypt a token for the current Windows user with DPAPI."""

    _require_windows()
    raw = (token or "").encode("utf-8")
    if not raw:
        return ""
    input_blob, input_buffer = _blob_from_bytes(raw)
    entropy_blob, entropy_buffer = _blob_from_bytes(_ENTROPY)
    output_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        _DESCRIPTION,
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    # Keep buffers alive through the native call.
    del input_buffer, entropy_buffer
    if not ok:
        raise CredentialError(f"Windows DPAPI 加密失败，错误码 {ctypes.GetLastError()}。")
    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))


def unprotect_token(value: str) -> str:
    """Decrypt a token protected by :func:`protect_token`."""

    _require_windows()
    if not value:
        return ""
    try:
        encrypted = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise CredentialError("保存的 GitHub 令牌格式无效。") from exc
    input_blob, input_buffer = _blob_from_bytes(encrypted)
    entropy_blob, entropy_buffer = _blob_from_bytes(_ENTROPY)
    output_blob = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer, entropy_buffer
    if not ok:
        raise CredentialError(f"Windows DPAPI 解密失败，错误码 {ctypes.GetLastError()}。")
    try:
        decrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return decrypted.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialError("保存的 GitHub 令牌无法解码。") from exc
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))
