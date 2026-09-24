"""Pops queued trials and launches them as Jobs, never exceeding max_concurrency."""

import logging
import time

from app.k8s import JobLauncher
from app.queue import RedisTrialQueue, TrialQueue
from app.settings import settings

log = logging.getLogger("dispatcher")


def dispatch_once(queue: TrialQueue, launcher: JobLauncher, max_concurrency: int) -> bool:
    """Launch at most one trial. Returns True if a trial was launched."""
    if launcher.active_count() >= max_concurrency:
        return False
    item = queue.pop(timeout=5)
    if item is None:
        return False
    try:
        launcher.launch(item.trial_id, item.callback_token)
    except Exception:
        log.exception("launch failed for trial %s; requeueing", item.trial_id)
        queue.push_front(item)
        return False
    log.info("launched trial %s", item.trial_id)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    queue = RedisTrialQueue(settings.redis_url, settings.queue_name)
    launcher = JobLauncher(settings)
    log.info("dispatcher up: namespace=%s max_concurrency=%d", settings.namespace, settings.max_concurrency)
    while True:
        try:
            launched = dispatch_once(queue, launcher, settings.max_concurrency)
        except Exception:
            # Redis or the Kubernetes API briefly unavailable (e.g. at startup): back off, don't crash.
            log.exception("dispatch loop error; retrying")
            launched = False
            time.sleep(4)
        if not launched:
            time.sleep(1)


if __name__ == "__main__":
    main()
