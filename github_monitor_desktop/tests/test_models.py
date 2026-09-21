from __future__ import annotations

import unittest

from github_monitor_desktop.models import (
    RELEASE_ASSET_PLATFORM_LABELS,
    ConfigError,
    MonitorConfig,
    classify_release_asset,
    parse_github_repo_url,
    parse_patterns,
)


class ModelTests(unittest.TestCase):
    def test_repository_url_variants(self):
        expected = ("Given-Dream", "changedetection.io", "https://github.com/Given-Dream/changedetection.io")
        self.assertEqual(parse_github_repo_url("Given-Dream/changedetection.io"), expected)
        self.assertEqual(parse_github_repo_url("git@github.com:Given-Dream/changedetection.io.git"), expected)
        self.assertEqual(parse_github_repo_url("https://github.com/Given-Dream/changedetection.io/blob/master/README.md"), expected)

    def test_rejects_non_github_and_parent_path(self):
        with self.assertRaises(ConfigError):
            parse_github_repo_url("https://example.com/owner/repo")
        with self.assertRaises(ConfigError):
            parse_patterns("../secret.txt")

    def test_patterns_are_normalized_and_deduplicated(self):
        self.assertEqual(parse_patterns(".github\\workflows\\*.yml; pyproject.toml;pyproject.toml"), [".github/workflows/*.yml", "pyproject.toml"])

    def test_release_asset_platform_is_inferred_from_name_or_extension(self):
        cases = {
            "tool-windows-x64.zip": "windows",
            "tool_win-arm64.msi": "windows",
            "tool-darwin-arm64.tar.gz": "macos",
            "tool-macos-universal.dmg": "macos",
            "tool-linux-x86_64.tar.gz": "linux",
            "tool-x86_64.AppImage": "linux",
            "checksums.txt": "other",
            "tool-portable.zip": "other",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(classify_release_asset(name), expected)

    def test_old_config_defaults_to_all_release_asset_platforms(self):
        config = MonitorConfig.from_dict(
            {
                "repo_url": "https://github.com/owner/repo",
                "owner": "owner",
                "repo": "repo",
                "download_dir": "C:/downloads",
                "resources": ["releases"],
            }
        )
        self.assertEqual(config.release_asset_platforms, list(RELEASE_ASSET_PLATFORM_LABELS))

    def test_release_asset_download_requires_a_selected_platform(self):
        config = MonitorConfig(
            repo_url="https://github.com/owner/repo",
            owner="owner",
            repo="repo",
            download_dir="C:/downloads",
            resources=["releases"],
            download_release_assets=True,
            release_asset_platforms=[],
        )
        with self.assertRaises(ConfigError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
