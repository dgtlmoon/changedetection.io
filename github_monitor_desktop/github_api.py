from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_BASE = "https://api.github.com"
GRAPHQL_URL = f"{API_BASE}/graphql"
API_VERSION = "2022-11-28"
USER_AGENT = "GitHubMonitorDesktop/1.0"


class SafeRedirectHandler(HTTPRedirectHandler):
    """Follow HTTPS downloads without forwarding a GitHub token off-host."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        redirected = super().redirect_request(request, file_pointer, code, message, headers, new_url)
        if redirected is None:
            return None
        parsed = urlparse(redirected.full_url)
        if parsed.scheme != "https":
            raise GitHubAPIError("拒绝跟随非 HTTPS 下载重定向。", endpoint=redirected.full_url)
        old_host = (urlparse(request.full_url).hostname or "").lower()
        new_host = (parsed.hostname or "").lower()
        if new_host != old_host:
            redirected.remove_header("Authorization")
        return redirected


@dataclass
class ResponseMeta:
    status: int
    etag: str | None = None
    rate_remaining: int | None = None
    rate_reset: int | None = None


class GitHubAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        endpoint: str = "",
        rate_remaining: int | None = None,
        rate_reset: int | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.endpoint = endpoint
        self.rate_remaining = rate_remaining
        self.rate_reset = rate_reset


class AuthenticationRequired(GitHubAPIError):
    pass


class RateLimitExceeded(GitHubAPIError):
    pass


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class GitHubClient:
    def __init__(
        self,
        token: str = "",
        *,
        timeout: int = 30,
        opener: Callable | None = None,
        max_attempts: int = 3,
        retry_backoff: float = 0.75,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.token = (token or "").strip()
        self.timeout = timeout
        self._opener = opener or build_opener(SafeRedirectHandler()).open
        self.max_attempts = max(1, int(max_attempts))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self._sleep = sleep
        self.last_meta: ResponseMeta | None = None
        self.minimum_rate_remaining: int | None = None
        self.rate_reset: int | None = None
        self.rate_limited = False

    def _record_rate(self, remaining: int | None, reset: int | None) -> None:
        if remaining is not None:
            if self.minimum_rate_remaining is None:
                self.minimum_rate_remaining = remaining
            else:
                self.minimum_rate_remaining = min(self.minimum_rate_remaining, remaining)
        if reset is not None:
            self.rate_reset = reset

    def _headers(self, *, accept: str, etag: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    @staticmethod
    def _validate_api_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise GitHubAPIError("拒绝访问非 api.github.com 地址。", endpoint=url)
        return url

    def _url(self, endpoint: str) -> str:
        if endpoint.startswith("https://"):
            return self._validate_api_url(endpoint)
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return API_BASE + endpoint

    def _request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        accept: str = "application/vnd.github+json",
        etag: str | None = None,
    ):
        url = self._url(endpoint)
        request = Request(
            url,
            data=data,
            method=method,
            headers=self._headers(accept=accept, etag=etag),
        )
        for attempt in range(self.max_attempts):
            try:
                response = self._opener(request, timeout=self.timeout)
                headers = response.headers
                self.last_meta = ResponseMeta(
                    status=getattr(response, "status", 200),
                    etag=headers.get("ETag"),
                    rate_remaining=_as_int(headers.get("X-RateLimit-Remaining")),
                    rate_reset=_as_int(headers.get("X-RateLimit-Reset")),
                )
                self._record_rate(self.last_meta.rate_remaining, self.last_meta.rate_reset)
                return response
            except HTTPError as exc:
                remaining = _as_int(exc.headers.get("X-RateLimit-Remaining")) if exc.headers else None
                reset = _as_int(exc.headers.get("X-RateLimit-Reset")) if exc.headers else None
                self._record_rate(remaining, reset)
                if exc.code == 304:
                    self.last_meta = ResponseMeta(304, etag=etag, rate_remaining=remaining, rate_reset=reset)
                    return None
                if exc.code in {408, 429, 500, 502, 503, 504} and attempt + 1 < self.max_attempts:
                    retry_after = _as_int(exc.headers.get("Retry-After")) if exc.headers else None
                    exc.close()
                    delay = float(retry_after) if retry_after is not None else self.retry_backoff * (2**attempt)
                    self._sleep(min(delay, 30.0))
                    continue
                try:
                    payload = json.loads(exc.read().decode("utf-8", errors="replace"))
                    api_message = payload.get("message") or str(exc)
                except (ValueError, OSError):
                    api_message = str(exc)
                message = f"GitHub API {exc.code}: {api_message}"
                kwargs = {
                    "status": exc.code,
                    "endpoint": url,
                    "rate_remaining": remaining,
                    "rate_reset": reset,
                }
                if exc.code in {401, 403} and remaining == 0:
                    self.rate_limited = True
                    raise RateLimitExceeded(message, **kwargs) from exc
                if exc.code in {401, 403}:
                    raise AuthenticationRequired(message, **kwargs) from exc
                raise GitHubAPIError(message, **kwargs) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self.max_attempts:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise GitHubAPIError(f"连接 GitHub API 失败（已重试 {self.max_attempts} 次）：{exc}", endpoint=url) from exc
        raise GitHubAPIError("连接 GitHub API 失败。", endpoint=url)

    def request_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        etag: str | None = None,
    ) -> tuple[object | None, ResponseMeta]:
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        response = self._request(endpoint, method=method, data=data, etag=etag)
        if response is None:
            return None, self.last_meta or ResponseMeta(304, etag=etag)
        try:
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
        return payload, self.last_meta or ResponseMeta(200)

    def request_bytes(
        self,
        endpoint: str,
        *,
        accept: str = "application/vnd.github.raw+json",
    ) -> tuple[bytes, ResponseMeta]:
        response = self._request(endpoint, accept=accept)
        if response is None:
            return b"", self.last_meta or ResponseMeta(304)
        try:
            payload = response.read()
        finally:
            response.close()
        return payload, self.last_meta or ResponseMeta(200)

    def download_to(
        self,
        endpoint: str,
        destination: str | Path,
        *,
        accept: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = self._request(endpoint, accept=accept)
        if response is None:
            raise GitHubAPIError("下载请求意外返回 304。", endpoint=endpoint)
        temporary: Path | None = None
        total = 0
        try:
            with tempfile.NamedTemporaryFile(delete=False, dir=str(destination.parent), prefix=".download-") as handle:
                temporary = Path(handle.name)
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if max_bytes is not None and total > max_bytes:
                        raise GitHubAPIError(f"下载内容超过限制（{max_bytes} 字节）。", endpoint=endpoint)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            return destination
        finally:
            response.close()
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _query(endpoint: str, **params) -> str:
        clean = {key: value for key, value in params.items() if value is not None}
        return endpoint + ("?" + urlencode(clean) if clean else "")

    def get_repository(self, owner: str, repo: str) -> dict:
        payload, _ = self.request_json(f"/repos/{quote(owner)}/{quote(repo)}")
        return dict(payload or {})

    def get_authenticated_user(self) -> dict:
        if not self.token:
            raise AuthenticationRequired("验证 GitHub 令牌需要先填写令牌。", status=401, endpoint=API_BASE + "/user")
        payload, _ = self.request_json("/user")
        return dict(payload or {})

    def get_readme(self, owner: str, repo: str, ref: str) -> tuple[dict, bytes]:
        endpoint = self._query(f"/repos/{quote(owner)}/{quote(repo)}/readme", ref=ref)
        payload, _ = self.request_json(endpoint)
        metadata = dict(payload or {})
        content = metadata.get("content")
        if metadata.get("encoding") == "base64" and isinstance(content, str):
            return metadata, base64.b64decode(content)
        raw, _ = self.request_bytes(endpoint)
        return metadata, raw

    def get_tree(self, owner: str, repo: str, ref: str) -> dict:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(ref, safe='')}",
            recursive=1,
        )
        payload, _ = self.request_json(endpoint)
        return dict(payload or {})

    def get_file(self, owner: str, repo: str, path: str, ref: str) -> bytes:
        encoded_path = quote(path, safe="/")
        endpoint = self._query(f"/repos/{quote(owner)}/{quote(repo)}/contents/{encoded_path}", ref=ref)
        payload, _ = self.request_bytes(endpoint)
        return payload

    def list_releases(self, owner: str, repo: str) -> list[dict]:
        endpoint = self._query(f"/repos/{quote(owner)}/{quote(repo)}/releases", per_page=100)
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def list_issues(self, owner: str, repo: str) -> list[dict]:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/issues",
            state="all",
            sort="updated",
            direction="desc",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return [dict(item) for item in list(payload or []) if "pull_request" not in item]

    def list_issue_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/issues/{int(number)}/comments",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def list_pulls(self, owner: str, repo: str) -> list[dict]:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/pulls",
            state="all",
            sort="updated",
            direction="desc",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def get_pull_diff(self, owner: str, repo: str, number: int) -> bytes:
        endpoint = f"/repos/{quote(owner)}/{quote(repo)}/pulls/{int(number)}"
        payload, _ = self.request_bytes(endpoint, accept="application/vnd.github.diff")
        return payload

    def list_pull_review_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/pulls/{int(number)}/comments",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def list_pull_reviews(self, owner: str, repo: str, number: int) -> list[dict]:
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/pulls/{int(number)}/reviews",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def list_security_alerts(self, owner: str, repo: str, kind: str) -> list[dict]:
        endpoints = {
            "dependabot": "dependabot/alerts",
            "code_scanning": "code-scanning/alerts",
            "secret_scanning": "secret-scanning/alerts",
        }
        if kind not in endpoints:
            raise ValueError(f"Unknown security alert kind: {kind}")
        endpoint = self._query(
            f"/repos/{quote(owner)}/{quote(repo)}/{endpoints[kind]}",
            state="open",
            per_page=100,
        )
        payload, _ = self.request_json(endpoint)
        return list(payload or [])

    def list_discussions(self, owner: str, repo: str) -> list[dict]:
        if not self.token:
            raise AuthenticationRequired("监控 Discussions 需要 GitHub 令牌。", status=401, endpoint=GRAPHQL_URL)
        query = """
        query RepositoryDiscussions($owner: String!, $repo: String!) {
          repository(owner: $owner, name: $repo) {
            discussions(first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                id number title body createdAt updatedAt url upvoteCount
                author { login }
                category { name }
                answer { id body createdAt updatedAt url author { login } }
                comments(last: 100) {
                  totalCount
                  nodes { id body createdAt updatedAt url author { login } }
                }
              }
            }
          }
        }
        """
        payload, _ = self.request_json(
            GRAPHQL_URL,
            method="POST",
            body={"query": query, "variables": {"owner": owner, "repo": repo}},
        )
        response = dict(payload or {})
        if response.get("errors"):
            message = "; ".join(str(item.get("message", item)) for item in response["errors"])
            raise GitHubAPIError(f"GitHub GraphQL：{message}", endpoint=GRAPHQL_URL)
        repository = ((response.get("data") or {}).get("repository") or {})
        return list(((repository.get("discussions") or {}).get("nodes") or []))
