"""
Price History Cleanup Module (US-009)

This module provides background cleanup functionality for price history records.
It should be called periodically to maintain database size and performance.

The cleanup job deletes price history records older than the configured retention period
(default: 90 days).

Usage:
    # Run cleanup directly
    from tasks.price_history_cleanup import run_price_history_cleanup
    result = await run_price_history_cleanup(retention_days=90)

    # Schedule periodic cleanup in Flask app
    from tasks.price_history_cleanup import start_price_history_cleanup_thread
    start_price_history_cleanup_thread(datastore)
"""

import asyncio
import os
import threading
from typing import Any

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


# Default retention period in days
DEFAULT_RETENTION_DAYS = 90

# How often to run cleanup (default: once per day in seconds)
DEFAULT_CLEANUP_INTERVAL_SECONDS = 86400  # 24 hours


async def run_price_history_cleanup(
    database_url: str | None = None,
    retention_days: int | None = None,
) -> dict[str, Any]:
    """
    Run price history cleanup job.

    This function deletes price history records older than retention_days.

    Args:
        database_url: PostgreSQL connection URL. If not provided,
                     reads from DATABASE_URL environment variable.
        retention_days: Number of days to retain history.
                       If not provided, reads from PRICE_HISTORY_RETENTION_DAYS
                       environment variable or uses default (90 days).

    Returns:
        Dict with cleanup statistics:
        - 'success': True if cleanup completed successfully
        - 'deleted_count': Number of records deleted
        - 'retention_days': Retention period used
        - 'error': Error message if cleanup failed
    """
    from tasks.postgresql_store import PostgreSQLStore

    # Get database URL
    db_url = database_url or os.getenv('DATABASE_URL')
    if not db_url:
        return {
            'success': False,
            'deleted_count': 0,
            'retention_days': 0,
            'error': 'DATABASE_URL not provided',
        }

    # Get retention days from parameter, env var, or default
    if retention_days is None:
        retention_days = int(os.getenv('PRICE_HISTORY_RETENTION_DAYS', DEFAULT_RETENTION_DAYS))

    try:
        store = PostgreSQLStore(database_url=db_url, include_default_watches=False)
        await store.initialize()

        try:
            result = await store.cleanup_old_price_history(retention_days=retention_days)
            return {
                'success': True,
                'deleted_count': result['deleted_count'],
                'retention_days': retention_days,
                'error': None,
            }
        finally:
            await store.close()

    except Exception as e:
        logger.error(f"Price history cleanup failed: {e}")
        return {
            'success': False,
            'deleted_count': 0,
            'retention_days': retention_days,
            'error': str(e),
        }


def run_price_history_cleanup_sync(
    database_url: str | None = None,
    retention_days: int | None = None,
) -> dict[str, Any]:
    """
    Synchronous wrapper for run_price_history_cleanup.

    Creates an event loop and runs the async cleanup function.
    """
    return asyncio.run(run_price_history_cleanup(database_url, retention_days))


def start_price_history_cleanup_thread(
    exit_event: threading.Event | None = None,
    cleanup_interval_seconds: int | None = None,
    retention_days: int | None = None,
) -> threading.Thread:
    """
    Start a background thread that periodically cleans up old price history.

    The thread runs until exit_event is set.

    Args:
        exit_event: Threading event to signal thread shutdown.
                   If not provided, creates a new event.
        cleanup_interval_seconds: Seconds between cleanup runs.
                                 Default: 86400 (24 hours).
                                 Can also be set via PRICE_HISTORY_CLEANUP_INTERVAL env var.
        retention_days: Days to retain history. Default: 90.
                       Can also be set via PRICE_HISTORY_RETENTION_DAYS env var.

    Returns:
        The started background thread.

    Example:
        exit_event = threading.Event()
        thread = start_price_history_cleanup_thread(exit_event)
        # ... later, to stop the thread:
        exit_event.set()
        thread.join()
    """
    if exit_event is None:
        exit_event = threading.Event()

    if cleanup_interval_seconds is None:
        cleanup_interval_seconds = int(
            os.getenv('PRICE_HISTORY_CLEANUP_INTERVAL', DEFAULT_CLEANUP_INTERVAL_SECONDS)
        )

    if retention_days is None:
        retention_days = int(os.getenv('PRICE_HISTORY_RETENTION_DAYS', DEFAULT_RETENTION_DAYS))

    def cleanup_loop():
        """Background thread loop that runs cleanup periodically."""
        logger.info(
            f"Price history cleanup thread started. "
            f"Interval: {cleanup_interval_seconds}s, Retention: {retention_days} days"
        )

        # Wait a bit on startup before first cleanup
        # This allows the app to finish initializing
        initial_delay = 60  # 1 minute
        if exit_event.wait(initial_delay):
            logger.info("Price history cleanup thread shutting down (initial delay)")
            return

        while not exit_event.is_set():
            try:
                result = run_price_history_cleanup_sync(retention_days=retention_days)
                if result['success']:
                    logger.info(
                        f"Price history cleanup completed: "
                        f"deleted {result['deleted_count']} records older than {retention_days} days"
                    )
                else:
                    logger.warning(f"Price history cleanup failed: {result['error']}")
            except Exception as e:
                logger.error(f"Error in price history cleanup thread: {e}")

            # Wait for the next cleanup interval
            if exit_event.wait(cleanup_interval_seconds):
                logger.info("Price history cleanup thread shutting down")
                break

    thread = threading.Thread(
        target=cleanup_loop,
        daemon=True,
        name="PriceHistoryCleanup",
    )
    thread.start()
    return thread


# CLI for manual execution
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Clean up old price history records')
    parser.add_argument(
        '--retention-days',
        type=int,
        default=None,
        help=f'Days to retain history (default: {DEFAULT_RETENTION_DAYS})',
    )
    parser.add_argument(
        '--database-url',
        type=str,
        default=None,
        help='PostgreSQL connection URL (default: from DATABASE_URL env var)',
    )

    args = parser.parse_args()

    print("Running price history cleanup...")
    result = run_price_history_cleanup_sync(
        database_url=args.database_url,
        retention_days=args.retention_days,
    )

    if result['success']:
        print(
            f"Cleanup completed successfully. "
            f"Deleted {result['deleted_count']} records older than {result['retention_days']} days."
        )
    else:
        print(f"Cleanup failed: {result['error']}")
        exit(1)
