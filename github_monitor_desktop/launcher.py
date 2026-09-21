from __future__ import annotations

import argparse
import multiprocessing
import os
import tempfile
from pathlib import Path

from .credentials import protect_token, unprotect_token
from .models import MonitorConfig, parse_github_repo_url
from .storage import AppStorage


def self_test() -> int:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    root.destroy()
    token = "github-monitor-self-test-token"
    if unprotect_token(protect_token(token)) != token:
        return 3
    owner, repo, url = parse_github_repo_url("https://github.com/Given-Dream/changedetection.io")
    with tempfile.TemporaryDirectory(prefix="github-monitor-self-test-") as temporary:
        storage = AppStorage(Path(temporary))
        config = MonitorConfig(url, owner, repo, temporary, resources=["readme"])
        config.validate()
        storage.save_config({"jobs": [config.to_dict()]})
        loaded = storage.load_config()
        if loaded["jobs"][0]["repo"] != "changedetection.io":
            return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub 仓库更新监控与下载")
    parser.add_argument("--self-test", action="store_true", help="运行本地启动自检后退出")
    parser.add_argument("--gui-smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--api-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.api_smoke_test:
        from .github_api import GitHubAPIError, GitHubClient

        try:
            client = GitHubClient(timeout=20)
            repository = client.get_repository("Given-Dream", "changedetection.io")
            _metadata, content = client.get_readme("Given-Dream", "changedetection.io", repository["default_branch"])
            return 0 if content else 4
        except GitHubAPIError:
            return 5
    from .app import run_app

    if args.gui_smoke_test:
        previous_appdata = os.environ.get("APPDATA")
        try:
            with tempfile.TemporaryDirectory(prefix="github-monitor-gui-smoke-") as temporary:
                os.environ["APPDATA"] = temporary
                run_app(exit_after_ms=800, open_token_settings=True)
        finally:
            if previous_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous_appdata
    else:
        run_app()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
