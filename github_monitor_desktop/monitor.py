from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .github_api import GitHubAPIError, GitHubClient
from .models import CheckResult, MonitorConfig, MonitorEvent, RESOURCE_LABELS, classify_release_asset
from .storage import AppStorage


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _time_folder(value: str) -> str:
    return value.replace(":", "-").replace("Z", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_component(value: str, fallback: str = "item") -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    value = value[:120] or fallback
    stem = value.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    return "_" + value if stem in reserved else value


def _safe_relative(path: str) -> Path:
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"不安全的仓库文件路径：{path}")
    return Path(*(_safe_component(part) for part in pure.parts))


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")
    return path


def _write_bytes(path: Path, value: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def _login(value: Any) -> str:
    return str(value.get("login", "")) if isinstance(value, dict) else ""


def _labels(values: Any) -> list[dict]:
    result = []
    for value in values or []:
        if isinstance(value, dict):
            result.append(
                {
                    "name": value.get("name"),
                    "color": value.get("color"),
                    "description": value.get("description"),
                }
            )
    return sorted(result, key=lambda item: str(item.get("name") or ""))


def _issue_snapshot(item: dict) -> dict:
    milestone = item.get("milestone") or {}
    return {
        "id": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title"),
        "body": item.get("body"),
        "state": item.get("state"),
        "state_reason": item.get("state_reason"),
        "locked": item.get("locked"),
        "comments": item.get("comments"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "html_url": item.get("html_url"),
        "author": _login(item.get("user")),
        "assignees": sorted(_login(value) for value in item.get("assignees") or []),
        "labels": _labels(item.get("labels")),
        "milestone": {
            "number": milestone.get("number"),
            "title": milestone.get("title"),
            "state": milestone.get("state"),
        }
        if milestone
        else None,
    }


def _pull_snapshot(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title"),
        "body": item.get("body"),
        "state": item.get("state"),
        "draft": item.get("draft"),
        "locked": item.get("locked"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": item.get("merged_at"),
        "html_url": item.get("html_url"),
        "author": _login(item.get("user")),
        "assignees": sorted(_login(value) for value in item.get("assignees") or []),
        "requested_reviewers": sorted(_login(value) for value in item.get("requested_reviewers") or []),
        "labels": _labels(item.get("labels")),
        "head": (item.get("head") or {}).get("sha"),
        "base": (item.get("base") or {}).get("sha"),
    }


def _release_snapshot(item: dict) -> dict:
    assets = []
    for asset in item.get("assets") or []:
        assets.append(
            {
                "id": asset.get("id"),
                "name": asset.get("name"),
                "label": asset.get("label"),
                "size": asset.get("size"),
                "content_type": asset.get("content_type"),
                "updated_at": asset.get("updated_at"),
                "digest": asset.get("digest"),
                "url": asset.get("url"),
            }
        )
    return {
        "id": item.get("id"),
        "tag_name": item.get("tag_name"),
        "name": item.get("name"),
        "body": item.get("body"),
        "draft": item.get("draft"),
        "prerelease": item.get("prerelease"),
        "created_at": item.get("created_at"),
        "published_at": item.get("published_at"),
        "target_commitish": item.get("target_commitish"),
        "html_url": item.get("html_url"),
        "author": _login(item.get("author")),
        "assets": sorted(assets, key=lambda value: (str(value.get("name") or ""), str(value.get("id") or ""))),
        "zipball_url": item.get("zipball_url"),
    }


def _security_snapshot(item: dict, kind: str) -> dict:
    # API payloads contain no polling timestamp, so retaining the complete object
    # catches rule, dismissal, location and dependency changes without false clocks.
    return {"kind": kind, "payload": item}


def _discussion_snapshot(item: dict) -> dict:
    comments = []
    comment_block = item.get("comments") or {}
    for comment in comment_block.get("nodes") or []:
        comments.append(
            {
                "id": comment.get("id"),
                "body": comment.get("body"),
                "created_at": comment.get("createdAt"),
                "updated_at": comment.get("updatedAt"),
                "url": comment.get("url"),
                "author": _login(comment.get("author")),
            }
        )
    answer = item.get("answer") or {}
    return {
        "id": item.get("id"),
        "number": item.get("number"),
        "title": item.get("title"),
        "body": item.get("body"),
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "url": item.get("url"),
        "upvote_count": item.get("upvoteCount"),
        "author": _login(item.get("author")),
        "category": (item.get("category") or {}).get("name"),
        "answer": {
            "id": answer.get("id"),
            "body": answer.get("body"),
            "created_at": answer.get("createdAt"),
            "updated_at": answer.get("updatedAt"),
            "url": answer.get("url"),
            "author": _login(answer.get("author")),
        }
        if answer
        else None,
        "comments_total": comment_block.get("totalCount"),
        "comments": comments,
    }


def _mapping(values: list[dict], key: str) -> dict[str, dict]:
    return {str(value.get(key)): value for value in values if value.get(key) is not None}


def _changes(old: list[dict], new: list[dict], key: str) -> tuple[list[dict], list[dict], list[dict]]:
    old_map = _mapping(old, key)
    new_map = _mapping(new, key)
    added = [new_map[name] for name in sorted(new_map.keys() - old_map.keys())]
    removed = [old_map[name] for name in sorted(old_map.keys() - new_map.keys())]
    modified = [new_map[name] for name in sorted(new_map.keys() & old_map.keys()) if new_map[name] != old_map[name]]
    return added, modified, removed


class GitHubMonitor:
    def __init__(
        self,
        storage: AppStorage,
        client_factory: Callable[[str], GitHubClient] | None = None,
    ):
        self.storage = storage
        self.client_factory = client_factory or (lambda token: GitHubClient(token))

    def check(self, config: MonitorConfig, token: str = "") -> CheckResult:
        config.validate()
        checked_at = _now_iso()
        result = CheckResult(config.job_id, config.display_name, checked_at)
        client = self.client_factory(token)
        state = self.storage.load_state()
        job_state = state["jobs"].setdefault(
            config.job_id,
            {"repository": config.display_name, "resources": {}},
        )
        job_state["repository"] = config.display_name
        resource_states = job_state.setdefault("resources", {})

        try:
            repository = client.get_repository(config.owner, config.repo)
            default_branch = str(repository.get("default_branch") or "HEAD")
        except GitHubAPIError as exc:
            result.warnings.append(str(exc))
            self._copy_rate(client, result)
            return result

        for resource in config.resources:
            try:
                snapshot, context = self._fetch(resource, config, client, default_branch)
                previous = resource_states.get(resource)
                if resource == "security" and previous:
                    previous_snapshot = previous.get("snapshot") or {}
                    for kind in context.get("failed_kinds", []):
                        if kind in previous_snapshot:
                            snapshot[kind] = previous_snapshot[kind]
                for warning in context.get("partial_errors", []):
                    result.warnings.append(f"Security alerts 部分检查失败：{warning}")
                fingerprint = content_fingerprint(snapshot)
                if previous is None:
                    try:
                        paths = self._materialize_initial_latest(
                            resource,
                            snapshot,
                            context,
                            config,
                            client,
                            checked_at,
                        )
                        result.initialized_resources.append(resource)
                        result.initial_downloaded_paths.extend(paths)
                        record_snapshot = True
                    except (GitHubAPIError, OSError, ValueError) as exc:
                        result.warnings.append(f"{RESOURCE_LABELS[resource]} 首次下载失败：{exc}")
                        # Do not establish the baseline until its initial test
                        # download succeeds; the next check will retry it.
                        record_snapshot = False
                elif previous.get("fingerprint") != fingerprint:
                    record_snapshot = True
                    try:
                        events = self._materialize_changes(
                            resource,
                            previous.get("snapshot"),
                            snapshot,
                            context,
                            config,
                            client,
                            checked_at,
                        )
                        result.events.extend(events)
                    except (GitHubAPIError, OSError, ValueError) as exc:
                        result.warnings.append(f"{RESOURCE_LABELS[resource]} 下载失败：{exc}")
                        result.events.append(
                                self._category_event(resource, config, checked_at, "updated", details={"download_error": str(exc)})
                        )
                        # Retain the old fingerprint so a transient download
                        # failure is retried on the next scheduled check.
                        record_snapshot = False
                else:
                    record_snapshot = True
                if record_snapshot:
                    resource_states[resource] = {
                        "fingerprint": fingerprint,
                        "snapshot": snapshot,
                        "checked_at": checked_at,
                    }
            except (GitHubAPIError, OSError, ValueError, TypeError) as exc:
                result.warnings.append(f"{RESOURCE_LABELS[resource]} 检查失败：{exc}")

        # Stop retaining stale baselines for categories removed from this job.
        for resource in set(resource_states) - set(config.resources):
            resource_states.pop(resource, None)
        job_state["last_checked_at"] = checked_at
        self.storage.save_state(state)
        for event in result.events:
            self.storage.append_event(event.to_dict())
        self._copy_rate(client, result)
        return result

    @staticmethod
    def _copy_rate(client: GitHubClient, result: CheckResult) -> None:
        result.rate_limited = client.rate_limited
        result.rate_remaining = client.minimum_rate_remaining
        result.rate_reset = client.rate_reset

    def _fetch(
        self,
        resource: str,
        config: MonitorConfig,
        client: GitHubClient,
        default_branch: str,
    ) -> tuple[Any, Any]:
        if resource == "readme":
            metadata, content = client.get_readme(config.owner, config.repo, default_branch)
            snapshot = {
                "path": metadata.get("path") or "README.md",
                "sha": metadata.get("sha"),
                "size": len(content),
                "html_url": metadata.get("html_url") or f"{config.repo_url}#readme",
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
            return snapshot, {"content": content, "metadata": metadata}
        if resource == "configs":
            tree = client.get_tree(config.owner, config.repo, default_branch)
            if tree.get("truncated"):
                raise GitHubAPIError("仓库文件树被 GitHub 截断，已跳过以避免误报删除。")
            entries = []
            for item in tree.get("tree") or []:
                path = str(item.get("path") or "")
                if item.get("type") == "blob" and self._matches(path, config.config_patterns):
                    entries.append({"path": path, "sha": item.get("sha"), "size": item.get("size")})
            entries.sort(key=lambda value: value["path"])
            return entries, {"branch": default_branch}
        if resource == "releases":
            raw = client.list_releases(config.owner, config.repo)
            snapshot = sorted((_release_snapshot(item) for item in raw), key=lambda item: str(item.get("id") or ""))
            return snapshot, {"raw": raw}
        if resource == "issues":
            raw = client.list_issues(config.owner, config.repo)
            snapshot = sorted((_issue_snapshot(item) for item in raw), key=lambda item: int(item.get("number") or 0))
            return snapshot, {"raw": raw}
        if resource == "pulls":
            raw = client.list_pulls(config.owner, config.repo)
            snapshot = sorted((_pull_snapshot(item) for item in raw), key=lambda item: int(item.get("number") or 0))
            return snapshot, {"raw": raw}
        if resource == "security":
            raw: dict[str, list[dict]] = {}
            errors: list[str] = []
            failed_kinds: list[str] = []
            for kind in ("dependabot", "code_scanning", "secret_scanning"):
                try:
                    raw[kind] = client.list_security_alerts(config.owner, config.repo, kind)
                except GitHubAPIError as exc:
                    errors.append(f"{kind}: {exc}")
                    failed_kinds.append(kind)
            if not raw:
                raise GitHubAPIError("；".join(errors) or "无法读取安全告警。")
            snapshot = {
                kind: sorted(
                    (_security_snapshot(item, kind) for item in values),
                    key=self._security_key,
                )
                for kind, values in sorted(raw.items())
            }
            return snapshot, {"raw": raw, "partial_errors": errors, "failed_kinds": failed_kinds}
        if resource == "discussions":
            raw = client.list_discussions(config.owner, config.repo)
            snapshot = sorted((_discussion_snapshot(item) for item in raw), key=lambda item: int(item.get("number") or 0))
            return snapshot, {"raw": raw}
        raise ValueError(f"未知监控类型：{resource}")

    @staticmethod
    def _matches(path: str, patterns: list[str]) -> bool:
        pure = PurePosixPath(path)
        return any(pure.match(pattern) or fnmatch.fnmatchcase(path, pattern) for pattern in patterns)

    def _materialize_changes(
        self,
        resource: str,
        old: Any,
        new: Any,
        context: Any,
        config: MonitorConfig,
        client: GitHubClient,
        checked_at: str,
    ) -> list[MonitorEvent]:
        handlers = {
            "readme": self._readme_changes,
            "configs": self._config_changes,
            "releases": self._release_changes,
            "issues": self._issue_changes,
            "pulls": self._pull_changes,
            "security": self._security_changes,
            "discussions": self._discussion_changes,
        }
        return handlers[resource](old, new, context, config, client, checked_at)

    def _materialize_initial_latest(
        self,
        resource: str,
        snapshot: Any,
        context: Any,
        config: MonitorConfig,
        client: GitHubClient,
        checked_at: str,
    ) -> list[str]:
        """Download a bounded current sample before establishing a baseline."""
        initial_snapshot = snapshot
        initial_context = context
        empty: Any = []

        if resource == "readme":
            empty = {}
        elif resource == "configs":
            empty = []
        elif resource in {"releases", "issues", "pulls", "discussions"}:
            raw = list(context.get("raw") or [])
            if not raw:
                return []
            latest_raw = raw[0]
            if resource == "releases":
                initial_snapshot = [_release_snapshot(latest_raw)]
            elif resource == "issues":
                initial_snapshot = [_issue_snapshot(latest_raw)]
            elif resource == "pulls":
                initial_snapshot = [_pull_snapshot(latest_raw)]
            else:
                initial_snapshot = [_discussion_snapshot(latest_raw)]
            initial_context = dict(context)
            initial_context["raw"] = [latest_raw]
        elif resource == "security":
            empty = {}
            initial_snapshot = {}
            initial_raw: dict[str, list[dict]] = {}
            for kind, values in sorted((context.get("raw") or {}).items()):
                raw_values = list(values or [])
                initial_raw[kind] = raw_values[:1]
                initial_snapshot[kind] = [_security_snapshot(raw_values[0], kind)] if raw_values else []
            initial_context = dict(context)
            initial_context["raw"] = initial_raw

        events = self._materialize_changes(
            resource,
            empty,
            initial_snapshot,
            initial_context,
            config,
            client,
            checked_at,
        )
        return [path for event in events for path in event.downloaded_paths]

    def _base(self, config: MonitorConfig) -> Path:
        return Path(config.download_dir).expanduser().resolve() / config.repository_folder_name

    def _category_event(
        self,
        resource: str,
        config: MonitorConfig,
        checked_at: str,
        change_type: str,
        *,
        title: str | None = None,
        url: str | None = None,
        paths: list[Path] | None = None,
        details: dict | None = None,
    ) -> MonitorEvent:
        return MonitorEvent(
            job_id=config.job_id,
            repository=config.display_name,
            resource=resource,
            change_type=change_type,
            title=title or f"{RESOURCE_LABELS[resource]} 已更新",
            url=url or config.repo_url,
            detected_at=checked_at,
            downloaded_paths=[str(path) for path in paths or []],
            details=details or {},
        )

    def _readme_changes(self, old, new, context, config, client, checked_at):
        folder = self._base(config) / "README" / _time_folder(checked_at)
        filename = _safe_component(Path(str(new.get("path") or "README.md")).name, "README.md")
        content_path = _write_bytes(folder / filename, context["content"])
        metadata_path = _write_json(folder / "metadata.json", new)
        return [
            self._category_event(
                "readme",
                config,
                checked_at,
                "updated",
                title=f"README 内容已更新：{new.get('path')}",
                url=str(new.get("html_url") or config.repo_url),
                paths=[content_path, metadata_path],
                details={"old_sha": (old or {}).get("sha"), "new_sha": new.get("sha")},
            )
        ]

    def _config_changes(self, old, new, context, config, client, checked_at):
        added, modified, removed = _changes(old or [], new or [], "path")
        folder = self._base(config) / "configs" / _time_folder(checked_at)
        downloaded = []
        for item in added + modified:
            relative = _safe_relative(str(item["path"]))
            content = client.get_file(config.owner, config.repo, str(item["path"]), context["branch"])
            downloaded.append(_write_bytes(folder / relative, content))
        manifest = {
            "repository": config.display_name,
            "detected_at": checked_at,
            "added": added,
            "modified": modified,
            "removed": removed,
        }
        downloaded.append(_write_json(folder / "changes.json", manifest))
        summary = f"配置文件变化：新增 {len(added)}、修改 {len(modified)}、删除 {len(removed)}"
        return [
            self._category_event(
                "configs",
                config,
                checked_at,
                "updated",
                title=summary,
                url=config.repo_url,
                paths=downloaded,
                details={"added": [v["path"] for v in added], "modified": [v["path"] for v in modified], "removed": [v["path"] for v in removed]},
            )
        ]

    def _release_changes(self, old, new, context, config, client, checked_at):
        added, modified, removed = _changes(old or [], new or [], "id")
        events: list[MonitorEvent] = []
        raw_by_id = {str(item.get("id")): item for item in context["raw"]}
        for change_type, values in (("added", added), ("updated", modified)):
            for item in values:
                raw = raw_by_id.get(str(item.get("id")), item)
                tag = str(item.get("tag_name") or item.get("id") or "release")
                folder = self._base(config) / "releases" / _safe_component(tag) / _time_folder(checked_at)
                paths = [_write_json(folder / "release.json", raw)]
                markdown = f"# {item.get('name') or tag}\n\n- Tag: `{tag}`\n- Published: {item.get('published_at') or ''}\n- URL: {item.get('html_url') or ''}\n\n{item.get('body') or ''}\n"
                paths.append(_write_text(folder / "release.md", markdown))
                downloaded_assets: list[dict[str, str]] = []
                skipped_assets: list[dict[str, str]] = []
                if config.download_release_assets:
                    selected_platforms = set(config.release_asset_platforms)
                    for asset in raw.get("assets") or []:
                        raw_name = str(asset.get("name") or "asset")
                        platform = classify_release_asset(raw_name)
                        asset_summary = {"name": raw_name, "platform": platform}
                        if platform not in selected_platforms:
                            skipped_assets.append(asset_summary)
                            continue
                        endpoint = str(asset.get("url") or "")
                        if endpoint:
                            name = _safe_component(f"{asset.get('id') or 'asset'}-{raw_name}")
                            paths.append(client.download_to(endpoint, folder / "assets" / name))
                            downloaded_assets.append(asset_summary)
                if config.download_release_source:
                    endpoint = str(raw.get("zipball_url") or "")
                    if endpoint:
                        paths.append(client.download_to(endpoint, folder / f"source-{_safe_component(tag)}.zip"))
                events.append(
                    self._category_event(
                        "releases",
                        config,
                        checked_at,
                        change_type,
                        title=f"{'新 Release' if change_type == 'added' else 'Release 已更新'}：{item.get('name') or tag}",
                        url=str(item.get("html_url") or config.repo_url + "/releases"),
                        paths=paths,
                        details={
                            "tag": tag,
                            "asset_platforms": list(config.release_asset_platforms),
                            "downloaded_assets": downloaded_assets,
                            "skipped_assets": skipped_assets,
                        },
                    )
                )
        for item in removed:
            events.append(
                self._category_event(
                    "releases",
                    config,
                    checked_at,
                    "removed",
                    title=f"Release 已删除：{item.get('name') or item.get('tag_name')}",
                    url=config.repo_url + "/releases",
                    details={"tag": item.get("tag_name")},
                )
            )
        return events

    @staticmethod
    def _item_markdown(kind: str, item: dict) -> str:
        number = item.get("number")
        return (
            f"# {kind} #{number}: {item.get('title') or ''}\n\n"
            f"- State: {item.get('state') or ''}\n"
            f"- Author: {item.get('author') or ''}\n"
            f"- Updated: {item.get('updated_at') or ''}\n"
            f"- URL: {item.get('html_url') or item.get('url') or ''}\n\n"
            f"{item.get('body') or ''}\n"
        )

    def _list_item_changes(self, resource, old, new, config, checked_at):
        added, modified, _removed = _changes(old or [], new or [], "number")
        events = []
        for change_type, values in (("added", added), ("updated", modified)):
            for item in values:
                number = int(item.get("number") or 0)
                folder = self._base(config) / resource / str(number) / _time_folder(checked_at)
                paths = [
                    _write_json(folder / f"{resource[:-1]}.json", item),
                    _write_text(folder / f"{resource[:-1]}.md", self._item_markdown(resource[:-1].title(), item)),
                ]
                events.append(
                    self._category_event(
                        resource,
                        config,
                        checked_at,
                        change_type,
                        title=f"{RESOURCE_LABELS[resource]} #{number} {'新增' if change_type == 'added' else '已更新'}：{item.get('title')}",
                        url=str(item.get("html_url") or item.get("url") or config.repo_url),
                        paths=paths,
                        details={"number": number},
                    )
                )
        # A list API returns only the most recently updated 100 entries. Ignore
        # entries that merely fall out of that window to avoid a false alert.
        return events

    def _issue_changes(self, old, new, context, config, client, checked_at):
        events = self._list_item_changes("issues", old, new, config, checked_at)
        for event in events:
            number = int(event.details["number"])
            folder = Path(event.downloaded_paths[0]).parent
            comments = client.list_issue_comments(config.owner, config.repo, number)
            event.downloaded_paths.append(str(_write_json(folder / "comments.json", comments)))
        return events

    def _pull_changes(self, old, new, context, config, client, checked_at):
        events = self._list_item_changes("pulls", old, new, config, checked_at)
        for event in events:
            number = event.details.get("number")
            if not number:
                continue
            folder = Path(event.downloaded_paths[0]).parent
            diff = client.get_pull_diff(config.owner, config.repo, int(number))
            diff_path = _write_bytes(folder / "changes.diff", diff)
            event.downloaded_paths.append(str(diff_path))
            issue_comments = client.list_issue_comments(config.owner, config.repo, int(number))
            review_comments = client.list_pull_review_comments(config.owner, config.repo, int(number))
            reviews = client.list_pull_reviews(config.owner, config.repo, int(number))
            event.downloaded_paths.extend(
                [
                    str(_write_json(folder / "conversation-comments.json", issue_comments)),
                    str(_write_json(folder / "review-comments.json", review_comments)),
                    str(_write_json(folder / "reviews.json", reviews)),
                ]
            )
        return events

    @staticmethod
    def _security_key(item: dict) -> str:
        payload = item.get("payload") or {}
        return str(payload.get("number") or payload.get("id") or content_fingerprint(payload)[:16])

    def _security_changes(self, old, new, context, config, client, checked_at):
        events = []
        for kind in sorted(set((old or {}).keys()) | set((new or {}).keys())):
            old_values = old.get(kind, []) if old else []
            new_values = new.get(kind, []) if new else []
            old_map = {self._security_key(item): item for item in old_values}
            new_map = {self._security_key(item): item for item in new_values}
            for key in sorted(new_map.keys() | old_map.keys()):
                if key in new_map and key not in old_map:
                    change_type = "added"
                    item = new_map[key]
                elif key in old_map and key not in new_map:
                    change_type = "resolved"
                    item = old_map[key]
                elif new_map[key] != old_map[key]:
                    change_type = "updated"
                    item = new_map[key]
                else:
                    continue
                folder = self._base(config) / "security" / kind / _safe_component(key)
                path = _write_json(folder / f"{_time_folder(checked_at)}.json", item.get("payload") or item)
                events.append(
                    self._category_event(
                        "security",
                        config,
                        checked_at,
                        change_type,
                        title=f"{kind} 安全告警 {key}：{change_type}",
                        url=config.repo_url + "/security",
                        paths=[path],
                        details={"kind": kind, "key": key},
                    )
                )
        if context.get("partial_errors"):
            # The warning is persisted with the event record without turning a
            # successful subtype into a failed whole-category check.
            for event in events:
                event.details["partial_errors"] = context["partial_errors"]
        return events

    def _discussion_changes(self, old, new, context, config, client, checked_at):
        added, modified, _removed = _changes(old or [], new or [], "number")
        events = []
        for change_type, values in (("added", added), ("updated", modified)):
            for item in values:
                number = int(item.get("number") or 0)
                folder = self._base(config) / "discussions" / str(number) / _time_folder(checked_at)
                paths = [
                    _write_json(folder / "discussion.json", item),
                    _write_text(folder / "discussion.md", self._item_markdown("Discussion", item)),
                ]
                events.append(
                    self._category_event(
                        "discussions",
                        config,
                        checked_at,
                        change_type,
                        title=f"Discussion #{number} {'新增' if change_type == 'added' else '已更新'}：{item.get('title')}",
                        url=str(item.get("url") or config.repo_url + "/discussions"),
                        paths=paths,
                        details={"number": number},
                    )
                )
        return events
