from __future__ import annotations

import multiprocessing

from github_monitor_desktop.launcher import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
