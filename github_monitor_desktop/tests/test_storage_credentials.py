from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from github_monitor_desktop.credentials import protect_token, unprotect_token
from github_monitor_desktop.storage import AppStorage


class StorageCredentialTests(unittest.TestCase):
    def test_storage_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="github-monitor-storage-") as temporary:
            storage = AppStorage(Path(temporary))
            storage.save_config({"jobs": [{"job_id": "1"}]})
            storage.save_state({"jobs": {"1": {"value": 2}}})
            self.assertEqual(storage.load_config()["jobs"][0]["job_id"], "1")
            self.assertEqual(storage.load_state()["jobs"]["1"]["value"], 2)
            storage.delete_job_state("1")
            self.assertNotIn("1", storage.load_state()["jobs"])

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI only")
    def test_dpapi_round_trip_and_not_plaintext(self):
        token = "github_pat_test_value"
        protected = protect_token(token)
        self.assertNotIn(token, protected)
        self.assertEqual(unprotect_token(protected), token)


if __name__ == "__main__":
    unittest.main()
