"""
Debounced explicit garbage collection for the watch-check hot path.

Several places call gc.collect() after a check to keep C-level memory (pyppeteer buffers,
libxml2 documents, PIL, brotli) from accumulating. Individually each is reasonable. Run
concurrently by many fetch workers they become a storm: with FETCH_WORKERS=50 and roughly
five call sites per check, the process spends most of its time stopped in the collector,
because every gc.collect() is a full stop-the-world pass that walks the entire heap while
holding the GIL.

Measured on 153 real puppeteer checks of a live site, FETCH_WORKERS=50, an `//div` filter
so the lxml document tree is realistic:

                       collects  objects freed   gc time  checks/sec  CPU/check  RSS plateau
  one per call site         790      2,594,098     91.3s       0.766     1.373s      279.6MB
  debounced to 1s            48      2,219,010      7.3s       1.433     0.731s      275.3MB
  none at all                 0              0      0.0s       1.503     0.685s      287.7MB

Debouncing keeps 86% of the reclamation for 6% of the collections, and resident memory
ends up LOWER than collecting every time. It works because the collector is process-wide:
any worker's collection breaks every other worker's cycles too, so with many workers the
calls are overwhelmingly redundant duplicates rather than independently necessary.

Removing them entirely was also measured. It is slightly faster still, but it was the only
configuration whose RSS had not plateaued by the end of the run, so it is not offered.

Collecting a younger generation was measured and rejected: gen 0 freed 1,136 objects
against the full pass's 2,594,098, because objects that survive a 10-30 second fetch have
already been promoted out of gen 0. It is cheap because it does almost nothing.

Environment:
  EXPLICIT_GC_MIN_INTERVAL   seconds between explicit collections, process-wide.
                             Default 1.0. Set 0 to collect at every call site as before.
  EXPLICIT_GC_COLLECT        set false to disable explicit collection entirely. A
                             measurement switch for attributing a slowdown, not a
                             recommended setting - expect resident memory to drift.
"""

import gc
import os
import threading
import time

from changedetectionio.strtobool import strtobool

ENABLED = strtobool(os.getenv('EXPLICIT_GC_COLLECT', 'true'))
MIN_INTERVAL = float(os.getenv('EXPLICIT_GC_MIN_INTERVAL', '1.0') or 0)

_last_collect = 0.0
_lock = threading.Lock()


def collect(where=None):
    """Explicit collection for the per-check hot path, rate-limited process-wide.

    `where` is a short label for the call site, kept so callers read clearly and so a
    future caller can log it. Returns the number of objects collected, or 0 when the call
    was debounced or disabled - matching gc.collect()'s return, so this is a drop-in
    replacement for it.
    """
    global _last_collect

    if not ENABLED:
        return 0

    if MIN_INTERVAL > 0:
        now = time.monotonic()
        with _lock:
            if now - _last_collect < MIN_INTERVAL:
                return 0
            _last_collect = now

    return gc.collect()
