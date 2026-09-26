"""Crash-safe work queue of trial ids.

pop() atomically moves an id from the queue to a processing list (BLMOVE), so an id is never
held only in the dispatcher's memory. ack() removes it once the trial is launched; nack() puts it
back on failure; recover() returns everything left in processing (after a dispatcher crash) to the
front of the queue. Delivery is at-least-once, so consumers must be idempotent.
"""

from typing import Protocol

import redis


class TrialQueue(Protocol):
    def push(self, trial_id: int) -> None: ...
    def pop(self, timeout: int) -> int | None: ...
    def ack(self, trial_id: int) -> None: ...
    def nack(self, trial_id: int) -> None: ...
    def recover(self) -> int: ...


class RedisTrialQueue:
    def __init__(self, url: str, name: str):
        self._redis = redis.Redis.from_url(url)
        self._queue = name
        self._processing = f"{name}:processing"

    def push(self, trial_id: int) -> None:
        self._redis.rpush(self._queue, trial_id)

    def pop(self, timeout: int) -> int | None:
        item = self._redis.blmove(self._queue, self._processing, timeout, "LEFT", "RIGHT")
        return None if item is None else int(item)

    def ack(self, trial_id: int) -> None:
        self._redis.lrem(self._processing, 1, trial_id)

    def nack(self, trial_id: int) -> None:
        pipe = self._redis.pipeline()
        pipe.lrem(self._processing, 1, trial_id)
        pipe.lpush(self._queue, trial_id)
        pipe.execute()

    def recover(self) -> int:
        moved = 0
        while self._redis.lmove(self._processing, self._queue, "RIGHT", "LEFT") is not None:
            moved += 1
        return moved
