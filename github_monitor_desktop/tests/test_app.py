from __future__ import annotations

import unittest

from github_monitor_desktop.app import GitHubMonitorApp
from github_monitor_desktop.models import MonitorConfig, RESOURCE_LABELS


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeScheduler:
    def __init__(self):
        self.running = True
        self.updated_resources: list[list[str]] = []
        self.checked_job_ids: list[str] = []

    def update(self, jobs, _token):
        self.updated_resources.append(list(jobs[0].resources))

    def check_now(self, job_id):
        self.checked_job_ids.append(job_id)


class FakeStorage:
    def __init__(self):
        self.deleted_job_ids: list[str] = []

    def delete_job_state(self, job_id):
        self.deleted_job_ids.append(job_id)


class AppTests(unittest.TestCase):
    @staticmethod
    def config(resources):
        return MonitorConfig(
            repo_url="https://github.com/owner/repo",
            owner="owner",
            repo="repo",
            download_dir="C:/downloads",
            resources=list(resources),
            job_id="job-1",
        )

    def test_check_selected_commits_current_resources_before_tree_refresh(self):
        app = GitHubMonitorApp.__new__(GitHubMonitorApp)
        saved = self.config(RESOURCE_LABELS)
        current = self.config(["readme", "releases"])
        app.jobs = [saved]
        app.editing_job_id = saved.job_id
        app.scheduler = FakeScheduler()
        app.storage = FakeStorage()
        app.token_var = FakeVar("token")
        app.status_by_job = {}
        app.root = None
        app._selected_job = lambda: app.jobs[0]
        app._form_config = lambda: current
        app._persist_config = lambda: True
        refreshed_resources: list[list[str]] = []
        app._refresh_tree = lambda select_id=None: refreshed_resources.append(list(app.jobs[0].resources))
        messages: list[str] = []
        app._log = messages.append

        app._check_selected()

        self.assertEqual(app.jobs[0].resources, ["readme", "releases"])
        self.assertEqual(refreshed_resources, [["readme", "releases"], ["readme", "releases"]])
        self.assertEqual(app.scheduler.updated_resources[-1], ["readme", "releases"])
        self.assertEqual(app.scheduler.checked_job_ids, ["job-1"])
        self.assertIn("已保存当前设置", messages[-1])

    def test_combined_check_button_starts_monitoring_when_stopped(self):
        app = GitHubMonitorApp.__new__(GitHubMonitorApp)
        current = self.config(["readme"])
        app.jobs = [current]
        app.editing_job_id = current.job_id
        app.scheduler = FakeScheduler()
        app.scheduler.running = False
        app.storage = FakeStorage()
        app.token_var = FakeVar("")
        app.status_by_job = {}
        app.root = None
        app._selected_job = lambda: app.jobs[0]
        app._form_config = lambda: current
        app._persist_config = lambda: True
        app._refresh_tree = lambda select_id=None: None
        app._log = lambda _message: None
        starts: list[bool] = []

        def start_monitoring(log=True):
            starts.append(log)
            app.scheduler.running = True

        app._start_monitoring = start_monitoring

        app._check_selected()

        self.assertEqual(starts, [False])
        self.assertTrue(app.scheduler.running)
        self.assertEqual(app.scheduler.checked_job_ids, ["job-1"])

    def test_saving_new_repository_starts_first_test_automatically(self):
        app = GitHubMonitorApp.__new__(GitHubMonitorApp)
        current = self.config(["readme"])
        app.jobs = []
        app.scheduler = FakeScheduler()
        app.scheduler.running = False
        app.status_by_job = {}
        refreshed: list[str | None] = []
        messages: list[str] = []

        def commit_form_job():
            app.jobs.append(current)
            return current

        app._commit_form_job = commit_form_job
        app._refresh_tree = lambda select_id=None: refreshed.append(select_id)
        app._log = messages.append
        starts: list[bool] = []

        def start_monitoring(log=True):
            starts.append(log)
            app.scheduler.running = True

        app._start_monitoring = start_monitoring

        app._save_job()

        self.assertEqual(starts, [False])
        self.assertEqual(app.status_by_job["job-1"], "首次测试中…")
        self.assertEqual(refreshed[-1], "job-1")
        self.assertIn("自动开始首次测试", messages[-1])

    def test_token_settings_reject_empty_and_apply_trimmed_token(self):
        app = GitHubMonitorApp.__new__(GitHubMonitorApp)
        app.token_var = FakeVar("old-token")

        self.assertFalse(app._apply_token_from_settings("   "))
        self.assertEqual(app.token_var.get(), "old-token")
        self.assertTrue(app._apply_token_from_settings("  github_pat_new  "))
        self.assertEqual(app.token_var.get(), "github_pat_new")


if __name__ == "__main__":
    unittest.main()
