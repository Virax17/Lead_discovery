import asyncio
import os
import time

from app.services.storage import EXPORT_DIR, s3_enabled

EXPORT_FILE_TTL_SECONDS = 24 * 60 * 60
SWEEP_INTERVAL_SECONDS = 60 * 60


def sweep_expired_exports(now: float | None = None) -> list[str]:
    # When S3 storage is active, expiry is handled by the bucket's lifecycle
    # rule (see DEPLOYMENT.md) — the local sweep is a no-op in that mode.
    if s3_enabled():
        return []

    now = now if now is not None else time.time()
    removed: list[str] = []
    if not os.path.isdir(EXPORT_DIR):
        return removed

    for filename in os.listdir(EXPORT_DIR):
        path = os.path.join(EXPORT_DIR, filename)
        if not os.path.isfile(path):
            continue
        age = now - os.path.getmtime(path)
        if age > EXPORT_FILE_TTL_SECONDS:
            try:
                os.remove(path)
                removed.append(filename)
            except OSError:
                pass
    return removed


async def run_export_cleanup_loop():
    while True:
        sweep_expired_exports()
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
