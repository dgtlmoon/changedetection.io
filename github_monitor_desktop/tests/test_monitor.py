from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from github_monitor_desktop.github_api import GitHubAPIError, ResponseMeta
from github_monitor_desktop.models import MonitorConfig
from github_monitor_desktop.monitor import GitHubMonitor
from github_monitor_desktop.storage import AppStorage


class FakeClient:
    def __init__(self):
        self.last_meta = ResponseMeta(200, rate_remaining=4999, rate_reset=123)
        self.minimum_rate_remaining = 4999
        self.rate_reset = 123
        self.rate_limited = False
        self.readme_content = b"first\n"
        self.readme_sha = "sha-1"
        self.tree = []
        self.files: dict[str, bytes] = {}
        self.releases = []
        self.issues = []
        self.issue_comments = []
        self.pulls = []
        self.pull_review_comments = []
        self.pull_reviews = []
        self.security = {"dependabot": [], "code_scanning": [], "secret_scanning": []}
        self.security_errors: set[str] = set()
        self.discussions = []
        self.downloaded_urls: list[str] = []

    def get_repository(self, owner, repo):
        return {"default_branch": "master"}

    def get_readme(self, owner, repo, ref):
        return ({"path": "README.md", "sha": self.readme_sha, "html_url": "https://github.com/o/r#readme"}, self.readme_content)

    def get_tree(self, owner, repo, ref):
        return {"truncated": False, "tree": self.tree}

    def get_file(self, owner, repo, path, ref):
        return self.files[path]

    def list_releases(self, owner, repo):
        return self.releases

    def list_issues(self, owner, repo):
        return self.issues

    def list_pulls(self, owner, repo):
        return self.pulls

    def list_issue_comments(self, owner, repo, number):
        return self.issue_comments

    def get_pull_diff(self, owner, repo, number):
        return b"diff --git a/a b/a\n"

    def list_pull_review_comments(self, owner, repo, number):
        return self.pull_review_comments

    def list_pull_reviews(self, owner, repo, number):
        return self.pull_reviews

    def list_security_alerts(self, owner, repo, kind):
        if kind in self.security_errors:
            raise GitHubAPIError("forbidden", status=403)
        return self.security[kind]

    def list_discussions(self, owner, repo):
        return self.discussions

    def download_to(self, endpoint, destination, **_kwargs):
        self.downloaded_urls.append(endpoint)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(("download:" + endpoint).encode())
        return destination


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="github-monitor-test-")
        root = Path(self.temporary.name)
        self.storage = AppStorage(root / "state")
        self.downloads = root / "downloads"
        self.client = FakeClient()
        self.monitor = GitHubMonitor(self.storage, client_factory=lambda _token: self.client)

    def tearDown(self):
        self.temporary.cleanup()

    def config(self, resources, **kwargs):
        defaults = dict(
            repo_url="https://github.com/owner/repo",
            owner="owner",
            repo="repo",
            download_dir=str(self.downloads),
            resources=list(resources),
            job_id="job-1",
        )
        defaults.update(kwargs)
        return MonitorConfig(**defaults)

    def test_readme_baseline_then_real_change_downloads(self):
        config = self.config(["readme"])
        first = self.monitor.check(config)
        self.assertEqual(first.events, [])
        self.assertEqual(first.initialized_resources, ["readme"])
        self.assertEqual(len(first.initial_downloaded_paths), 2)
        self.assertTrue(all(Path(path).is_file() for path in first.initial_downloaded_paths))

        self.client.readme_content = b"second\n"
        self.client.readme_sha = "sha-2"
        second = self.monitor.check(config)
        self.assertEqual(len(second.events), 1)
        self.assertEqual(second.events[0].resource, "readme")
        self.assertTrue(all(Path(path).is_file() for path in second.events[0].downloaded_paths))

        third = self.monitor.check(config)
        self.assertEqual(third.events, [])

    def test_first_check_downloads_only_latest_list_items(self):
        config = self.config(
            ["configs", "releases", "issues", "pulls", "security", "discussions"],
            config_patterns=["*.toml"],
            download_release_assets=False,
            download_release_source=False,
        )
        self.client.tree = [
            {"type": "blob", "path": "first.toml", "sha": "1", "size": 1},
            {"type": "blob", "path": "second.toml", "sha": "2", "size": 1},
        ]
        self.client.files = {"first.toml": b"1", "second.toml": b"2"}
        self.client.releases = [
            {"id": 2, "tag_name": "v2", "name": "latest", "assets": []},
            {"id": 1, "tag_name": "v1", "name": "older", "assets": []},
        ]
        self.client.issues = [
            {"id": 2, "number": 2, "title": "latest issue", "state": "open"},
            {"id": 1, "number": 1, "title": "older issue", "state": "open"},
        ]
        self.client.pulls = [
            {"id": 2, "number": 2, "title": "latest pull", "state": "open"},
            {"id": 1, "number": 1, "title": "older pull", "state": "closed"},
        ]
        for kind in self.client.security:
            self.client.security[kind] = [{"number": 2, "state": "open"}, {"number": 1, "state": "open"}]
        self.client.discussions = [
            {"id": "D2", "number": 2, "title": "latest discussion", "body": "new", "comments": {"nodes": []}},
            {"id": "D1", "number": 1, "title": "older discussion", "body": "old", "comments": {"nodes": []}},
        ]

        result = self.monitor.check(config)

        self.assertEqual(result.events, [])
        self.assertEqual(result.initialized_resources, config.resources)
        paths = [Path(path).as_posix() for path in result.initial_downloaded_paths]
        self.assertTrue(any("/releases/v2/" in path for path in paths))
        self.assertFalse(any("/releases/v1/" in path for path in paths))
        self.assertTrue(any("/issues/2/" in path for path in paths))
        self.assertFalse(any("/issues/1/" in path for path in paths))
        self.assertTrue(any("/pulls/2/" in path for path in paths))
        self.assertFalse(any("/pulls/1/" in path for path in paths))
        self.assertTrue(any("/discussions/2/" in path for path in paths))
        self.assertFalse(any("/discussions/1/" in path for path in paths))
        self.assertEqual(sum("/security/" in path for path in paths), 3)

    def test_failed_first_download_does_not_establish_baseline(self):
        config = self.config(["configs"], config_patterns=["*.toml"])
        self.client.tree = [{"type": "blob", "path": "pyproject.toml", "sha": "1", "size": 1}]
        self.client.files = {"pyproject.toml": b"content"}
        original_get_file = self.client.get_file

        def fail_download(*_args):
            raise GitHubAPIError("temporary download failure")

        self.client.get_file = fail_download
        failed = self.monitor.check(config)
        self.assertEqual(failed.initialized_resources, [])
        self.assertTrue(any("首次下载失败" in warning for warning in failed.warnings))
        state = self.storage.load_state()
        self.assertNotIn("configs", state["jobs"][config.job_id]["resources"])

        self.client.get_file = original_get_file
        retried = self.monitor.check(config)
        self.assertEqual(retried.initialized_resources, ["configs"])
        self.assertTrue(retried.initial_downloaded_paths)

    def test_config_add_modify_delete_is_manifested(self):
        config = self.config(["configs"], config_patterns=["*.toml", "*.yml"])
        self.client.tree = [
            {"type": "blob", "path": "pyproject.toml", "sha": "1", "size": 1},
            {"type": "blob", "path": "old.yml", "sha": "2", "size": 1},
        ]
        self.client.files = {"pyproject.toml": b"a", "old.yml": b"old"}
        self.assertFalse(self.monitor.check(config).events)

        self.client.tree = [
            {"type": "blob", "path": "pyproject.toml", "sha": "3", "size": 2},
            {"type": "blob", "path": "new.yml", "sha": "4", "size": 3},
        ]
        self.client.files = {"pyproject.toml": b"bb", "new.yml": b"new"}
        result = self.monitor.check(config)
        self.assertEqual(len(result.events), 1)
        details = result.events[0].details
        self.assertEqual(details["added"], ["new.yml"])
        self.assertEqual(details["modified"], ["pyproject.toml"])
        self.assertEqual(details["removed"], ["old.yml"])
        self.assertTrue(any(Path(path).name == "changes.json" for path in result.events[0].downloaded_paths))

    def test_new_release_downloads_only_selected_asset_platform_and_source(self):
        config = self.config(["releases"], release_asset_platforms=["windows"])
        self.assertFalse(self.monitor.check(config).events)
        self.client.releases = [
            {
                "id": 7,
                "tag_name": "v1.0.0",
                "name": "Version 1",
                "body": "notes",
                "draft": False,
                "prerelease": False,
                "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                "zipball_url": "https://api.github.com/repos/owner/repo/zipball/v1.0.0",
                "assets": [
                    {"id": 9, "name": "tool-windows-x64.zip", "size": 5, "url": "https://api.github.com/repos/owner/repo/releases/assets/9"},
                    {"id": 10, "name": "tool-macos-arm64.dmg", "size": 5, "url": "https://api.github.com/repos/owner/repo/releases/assets/10"},
                    {"id": 11, "name": "tool-linux-x86_64.tar.gz", "size": 5, "url": "https://api.github.com/repos/owner/repo/releases/assets/11"},
                    {"id": 12, "name": "checksums.txt", "size": 5, "url": "https://api.github.com/repos/owner/repo/releases/assets/12"},
                ],
            }
        ]
        result = self.monitor.check(config)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].change_type, "added")
        self.assertEqual(len(result.events[0].downloaded_paths), 4)
        self.assertEqual(len(self.client.downloaded_urls), 2)
        self.assertEqual(
            result.events[0].details["downloaded_assets"],
            [{"name": "tool-windows-x64.zip", "platform": "windows"}],
        )
        self.assertEqual(
            {item["name"] for item in result.events[0].details["skipped_assets"]},
            {"tool-macos-arm64.dmg", "tool-linux-x86_64.tar.gz", "checksums.txt"},
        )

    def test_first_release_download_uses_selected_asset_platforms(self):
        config = self.config(
            ["releases"],
            release_asset_platforms=["macos"],
            download_release_source=False,
        )
        self.client.releases = [
            {
                "id": 7,
                "tag_name": "v1.0.0",
                "name": "Version 1",
                "assets": [
                    {"id": 9, "name": "tool-windows-x64.zip", "url": "https://api.github.com/assets/9"},
                    {"id": 10, "name": "tool-macos-arm64.dmg", "url": "https://api.github.com/assets/10"},
                ],
            }
        ]

        result = self.monitor.check(config)

        self.assertEqual(result.events, [])
        self.assertEqual(result.initialized_resources, ["releases"])
        self.assertEqual(self.client.downloaded_urls, ["https://api.github.com/assets/10"])
        names = {Path(path).name for path in result.initial_downloaded_paths}
        self.assertIn("10-tool-macos-arm64.dmg", names)
        self.assertNotIn("9-tool-windows-x64.zip", names)

    def test_issue_api_order_does_not_trigger_false_change(self):
        config = self.config(["issues"])
        issue1 = {"id": 1, "number": 1, "title": "one", "body": "a", "state": "open", "html_url": "u1"}
        issue2 = {"id": 2, "number": 2, "title": "two", "body": "b", "state": "open", "html_url": "u2"}
        self.client.issues = [issue1, issue2]
        self.assertFalse(self.monitor.check(config).events)
        self.client.issues = [issue2, issue1]
        self.assertFalse(self.monitor.check(config).events)

    def test_failed_security_subtype_keeps_its_previous_baseline(self):
        config = self.config(["security"])
        self.client.security["dependabot"] = [{"number": 1, "state": "open"}]
        self.assertFalse(self.monitor.check(config).events)
        self.client.security_errors.add("dependabot")
        result = self.monitor.check(config)
        self.assertFalse(result.events)
        self.assertTrue(any("dependabot" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
