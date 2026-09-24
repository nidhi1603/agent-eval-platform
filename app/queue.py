import json
from dataclasses import dataclass
from typing import Protocol

import redis


@dataclass(frozen=True)
class QueuedTrial:
    trial_id: int
    callback_token: str


class TrialQueue(Protocol):
    def push(self, item: QueuedTrial) -> None: ...
    def push_front(self, item: QueuedTrial) -> None: ...
    def pop(self, timeout: int) -> QueuedTrial | None: ...


class RedisTrialQueue:
    """FIFO work queue on a Redis list: RPUSH to enqueue, BLPOP to dequeue."""

    def __init__(self, url: str, name: str):
        self._redis = redis.Redis.from_url(url)
        self._name = name

    def push(self, item: QueuedTrial) -> None:
        self._redis.rpush(self._name, _encode(item))

    def push_front(self, item: QueuedTrial) -> None:
        self._redis.lpush(self._name, _encode(item))

    def pop(self, timeout: int) -> QueuedTrial | None:
        res = self._redis.blpop([self._name], timeout=timeout)
        if res is None:
            return None
        data = json.loads(res[1])
        return QueuedTrial(trial_id=data["trial_id"], callback_token=data["callback_token"])


def _encode(item: QueuedTrial) -> str:
    return json.dumps({"trial_id": item.trial_id, "callback_token": item.callback_token})
