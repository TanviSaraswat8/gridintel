"""Cache + rate-limit backend: Redis when REDIS_URL is set and reachable, otherwise in-process memory."""
from __future__ import annotations

import json
import logging
import threading
import time

log = logging.getLogger("gridintel.cache")


class MemoryBackend:
    name = "memory"

    def __init__(self):
        self._d: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, k):
        with self._lock:
            v = self._d.get(k)
            if not v:
                return None
            if v[0] and v[0] < time.time():
                self._d.pop(k, None)
                return None
            return v[1]

    def set(self, k, v, ttl=None):
        with self._lock:
            self._d[k] = ((time.time() + ttl) if ttl else 0, v)

    def incr_window(self, k, window):
        with self._lock:
            now = time.time()
            exp, v = self._d.get(k, (0, "0"))
            if exp < now:
                exp, v = now + window, "0"
            v = str(int(v) + 1)
            self._d[k] = (exp, v)
            return int(v)

    def ping(self):
        return True


class RedisBackend:
    name = "redis"

    def __init__(self, url):
        import redis
        self.r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1, decode_responses=True)
        self.r.ping()

    def get(self, k):
        return self.r.get(k)

    def set(self, k, v, ttl=None):
        self.r.set(k, v, ex=ttl)

    def incr_window(self, k, window):
        p = self.r.pipeline()
        p.incr(k)
        p.expire(k, window, nx=True)
        return int(p.execute()[0])

    def ping(self):
        return bool(self.r.ping())


_backend = None


def init_cache(url: str):
    global _backend
    if url:
        try:
            _backend = RedisBackend(url)
            log.info("cache backend: redis")
            return _backend
        except Exception as e:  # pragma: no cover - depends on infra
            log.warning(f"Redis unavailable ({e}); falling back to in-memory cache")
    _backend = MemoryBackend()
    return _backend


def cache():
    return _backend or init_cache("")


def get_json(k):
    v = cache().get(k)
    return json.loads(v) if v else None


def set_json(k, v, ttl=None):
    cache().set(k, json.dumps(v, default=str), ttl)
