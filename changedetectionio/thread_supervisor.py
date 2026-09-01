"""
Keep critical background threads alive.

A threading.Thread cannot be restarted. Once its target returns, the thread is
finished and calling start() again raises RuntimeError("threads can only be
started once"). There is no built-in "respawn on death" option. So recovery has
to be built into the target itself.

This matters because a background loop can die in two ways that look identical
from outside, and both are silent:

  - it raises, and the traceback goes nowhere because nobody joins a daemon thread
  - it simply `return`s, e.g. a stray `return False` deep inside the loop body

The second is how the ticker thread stopped scheduling every watch in the app:
one watch with an unresolvable timezone hit `return False`, the whole loop
exited, and no watch was ever checked again until the process restarted. Nothing
was logged above ERROR, and the process stayed up and healthy-looking.

supervise() wraps a target so that any exit which is NOT a real shutdown is
logged CRITICAL and the target is re-entered, with exponential backoff so a
target that fails instantly cannot spin the CPU.
"""

import time

from loguru import logger

# Back off 1, 2, 4 ... up to this many seconds between restarts.
DEFAULT_MAX_BACKOFF_SECONDS = 60

# A target that stayed up at least this long is considered to have recovered,
# so its backoff resets rather than continuing to grow.
HEALTHY_RUNTIME_SECONDS = 60


def supervise(target, name, exit_event, is_shutting_down=None,
              max_backoff=DEFAULT_MAX_BACKOFF_SECONDS,
              healthy_after=HEALTHY_RUNTIME_SECONDS,
              _on_restart=None):
    """
    Run `target` forever, restarting it if it ever returns or raises.

    Never restarts once shutdown has begun - an exiting target is expected then,
    and respawning it would fight the shutdown path and delay process exit.

    Args:
        target:       zero-arg callable expected to loop until shutdown
        name:         thread name, used in log messages
        exit_event:   threading.Event - the primary shutdown signal
        is_shutting_down: optional extra zero-arg predicate returning True during
                      shutdown. sigshutdown_handler() sets both app.config.exit
                      and datastore.stop_thread, so pass the latter here to be
                      certain a restart can never race a shutdown.
        max_backoff:  ceiling for the restart delay, in seconds
        healthy_after: runtime after which the backoff resets to 1s
        _on_restart:  test hook, called with (restart_count, reason) before each retry

    Returns:
        None - only once shutdown is signalled
    """
    def stopping():
        if exit_event.is_set():
            return True
        if is_shutting_down is not None:
            try:
                return bool(is_shutting_down())
            except Exception:
                # A broken predicate must not keep a healthy thread from restarting
                return False
        return False

    backoff = 1
    restarts = 0

    while not stopping():
        started = time.monotonic()
        reason = None

        try:
            target()
            # Falling out of the target is only legitimate during shutdown.
            if stopping():
                break
            reason = "returned unexpectedly (a stray `return` inside its loop?)"
            logger.critical(
                f"{name} {reason} - this thread must run until shutdown. Restarting it."
            )
        except Exception as e:
            if stopping():
                break
            reason = f"crashed: {type(e).__name__}: {e}"
            logger.opt(exception=True).critical(f"{name} {reason} - restarting it.")

        ran_for = time.monotonic() - started
        backoff = 1 if ran_for >= healthy_after else min(backoff * 2, max_backoff)
        restarts += 1

        if _on_restart:
            _on_restart(restarts, reason)

        logger.critical(
            f"{name} restart #{restarts} in {backoff}s (previous run lasted {ran_for:.1f}s)"
        )
        # wait() returns True immediately once shutdown is requested
        if exit_event.wait(backoff) or stopping():
            break

    logger.info(f"{name} supervisor exiting - shutdown requested "
                f"(after {restarts} restart(s))")


def start_supervised_thread(target, name, exit_event, is_shutting_down=None, **kwargs):
    """
    Start `target` in a daemon thread wrapped in supervise().

    Returns:
        threading.Thread: the started thread (unlike Thread(...).start(), which
        returns None - assigning that to a module global is why nothing could
        ever check the ticker thread's is_alive()).
    """
    import threading

    thread = threading.Thread(
        target=supervise,
        args=(target, name, exit_event),
        kwargs={'is_shutting_down': is_shutting_down, **kwargs},
        daemon=True,
        name=name,
    )
    thread.start()
    return thread
