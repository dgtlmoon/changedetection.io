from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


RESOURCE_LABELS = {
    "readme": "README",
    "configs": "配置文件",
    "releases": "Releases",
    "issues": "Issues",
    "pulls": "Pull requests",
    "security": "Security alerts",
    "discussions": "Discussions",
}

RELEASE_ASSET_PLATFORM_LABELS = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
    "other": "其他/通用",
}

DEFAULT_CONFIG_PATTERNS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".github/dependabot.yml",
    ".github/CODEOWNERS",
    "Dockerfile",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements*.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "*.ini",
    "*.cfg",
    "*.toml",
)

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_WINDOWS_ASSET_SUFFIXES = (".exe", ".msi", ".msix", ".appx", ".appxbundle", ".cab")
_MACOS_ASSET_SUFFIXES = (".dmg", ".pkg", ".app.zip")
_LINUX_ASSET_SUFFIXES = (".appimage", ".deb", ".rpm", ".snap", ".flatpak")


class ConfigError(ValueError):
    """Raised when a monitor configuration is invalid."""


def parse_github_repo_url(value: str) -> tuple[str, str, str]:
    """Return ``(owner, repo, canonical_url)`` for a GitHub repository URL."""

    raw = (value or "").strip()
    if not raw:
        raise ConfigError("请输入 GitHub 仓库 URL。")

    if raw.startswith("git@github.com:"):
        raw = "https://github.com/" + raw.split(":", 1)[1]
    elif "://" not in raw and raw.count("/") == 1:
        raw = "https://github.com/" + raw

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ConfigError("仅支持 http、https 或 git@github.com 格式的 GitHub URL。")
    if (parsed.hostname or "").lower() not in {"github.com", "www.github.com"}:
        raise ConfigError("URL 必须指向 github.com。")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ConfigError("GitHub URL 中缺少 owner/repository。")
    owner = parts[0]
    repo = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    if not _OWNER_RE.fullmatch(owner) or not _REPO_RE.fullmatch(repo):
        raise ConfigError("GitHub owner 或 repository 名称格式不正确。")

    return owner, repo, f"https://github.com/{owner}/{repo}"


def parse_patterns(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        candidates = re.split(r"[;\n,]+", value)
    else:
        candidates = list(value)
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        pattern = str(candidate).strip().replace("\\", "/")
        if not pattern or pattern in seen:
            continue
        if pattern.startswith("/") or ".." in Path(pattern).parts:
            raise ConfigError(f"配置文件匹配规则不安全：{pattern}")
        seen.add(pattern)
        result.append(pattern)
    return result


def classify_release_asset(name: str) -> str:
    """Infer a release asset platform from its file name and extension."""

    normalized = str(name or "").strip().lower()
    tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if token}

    if normalized.endswith(_WINDOWS_ASSET_SUFFIXES) or tokens.intersection({"windows", "win", "win32", "win64"}):
        return "windows"
    if normalized.endswith(_MACOS_ASSET_SUFFIXES) or tokens.intersection({"mac", "macos", "darwin", "osx"}):
        return "macos"
    if normalized.endswith(_LINUX_ASSET_SUFFIXES) or tokens.intersection({"linux", "manylinux", "gnu", "appimage"}):
        return "linux"
    return "other"


@dataclass
class MonitorConfig:
    repo_url: str
    owner: str
    repo: str
    download_dir: str
    interval_minutes: int = 15
    resources: list[str] = field(default_factory=lambda: list(RESOURCE_LABELS))
    config_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_CONFIG_PATTERNS))
    download_release_assets: bool = True
    download_release_source: bool = True
    release_asset_platforms: list[str] = field(default_factory=lambda: list(RELEASE_ASSET_PLATFORM_LABELS))
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self) -> None:
        parsed_owner, parsed_repo, canonical = parse_github_repo_url(self.repo_url)
        if parsed_owner.lower() != self.owner.lower() or parsed_repo.lower() != self.repo.lower():
            raise ConfigError("仓库 URL 与 owner/repository 不一致。")
        self.repo_url = canonical
        if not self.download_dir.strip():
            raise ConfigError("请选择下载目录。")
        if not 1 <= int(self.interval_minutes) <= 10080:
            raise ConfigError("检查间隔必须在 1 到 10080 分钟之间。")
        unknown = set(self.resources) - set(RESOURCE_LABELS)
        if unknown:
            raise ConfigError(f"未知监控类型：{', '.join(sorted(unknown))}")
        if not self.resources:
            raise ConfigError("请至少选择一个监控类型。")
        self.config_patterns = parse_patterns(self.config_patterns)
        if "configs" in self.resources and not self.config_patterns:
            raise ConfigError("监控配置文件时，至少需要一个匹配规则。")
        selected_platforms = set(self.release_asset_platforms or [])
        unknown_platforms = selected_platforms - set(RELEASE_ASSET_PLATFORM_LABELS)
        if unknown_platforms:
            raise ConfigError(f"未知 Release 附件平台：{', '.join(sorted(unknown_platforms))}")
        self.release_asset_platforms = [
            name for name in RELEASE_ASSET_PLATFORM_LABELS if name in selected_platforms
        ]
        if self.download_release_assets and not self.release_asset_platforms:
            raise ConfigError("下载 Release 附件时，请至少选择一个附件版本。")

    @property
    def display_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def repository_folder_name(self) -> str:
        return f"{self.owner}__{self.repo}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> "MonitorConfig":
        allowed = {
            "repo_url",
            "owner",
            "repo",
            "download_dir",
            "interval_minutes",
            "resources",
            "config_patterns",
            "download_release_assets",
            "download_release_source",
            "release_asset_platforms",
            "job_id",
        }
        config = cls(**{key: item for key, item in value.items() if key in allowed})
        config.validate()
        return config


@dataclass
class MonitorEvent:
    job_id: str
    repository: str
    resource: str
    change_type: str
    title: str
    url: str
    detected_at: str
    downloaded_paths: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckResult:
    job_id: str
    repository: str
    checked_at: str
    events: list[MonitorEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    initialized_resources: list[str] = field(default_factory=list)
    initial_downloaded_paths: list[str] = field(default_factory=list)
    rate_remaining: int | None = None
    rate_reset: int | None = None
    rate_limited: bool = False
