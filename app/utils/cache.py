import functools
import hashlib
import inspect
import json
import logging
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional

from fastapi import HTTPException, Response

from app.settings import settings
from app.utils.breaker import bot_breaker
from app.utils.exceptions import BotChallengeError

logger = logging.getLogger(__name__)

# Named TTL tiers, resolved per call so environment overrides apply without re-importing.
TTL_TIERS = {
    "short": lambda: settings.CACHE_TTL_SHORT,
    "medium": lambda: settings.CACHE_TTL_MEDIUM,
    "long": lambda: settings.CACHE_TTL_LONG,
    "archive": lambda: settings.CACHE_TTL_ARCHIVE,
}


def current_season_id() -> int:
    """
    Return the Transfermarkt id of the season currently in progress.

    Season ids are the starting year, so 2025 means 2025/26. European seasons roll over in July.

    Returns:
        int: The current season id.
    """
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def is_past_season(season_id: Any) -> bool:
    """
    Determine whether a season id refers to a completed season.

    Completed seasons never change, so their responses can be cached far more aggressively.

    Args:
        season_id (Any): The season id to check; None means "current season".

    Returns:
        bool: True if the season has finished.
    """
    if season_id is None:
        return False
    try:
        return int(season_id) < current_season_id()
    except (TypeError, ValueError):
        return False


@dataclass
class CacheEntry:
    """
    A single cached endpoint response, or a cached negative result.

    Attributes:
        value (Any): The cached response payload, or the HTTPException for a negative entry.
        stored_at (float): Wall-clock time the entry was written.
        ttl (float): Seconds the entry is considered fresh.
        is_error (bool): True when the entry holds an HTTPException rather than a payload.
        etag (str): Weak validator derived from the payload.
    """

    value: Any
    stored_at: float
    ttl: float
    is_error: bool = False
    etag: str = field(default="")

    def age(self, now: float) -> float:
        """
        Return how long ago the entry was written.

        Args:
            now (float): The current time.

        Returns:
            float: Age in seconds.
        """
        return max(0.0, now - self.stored_at)

    def is_fresh(self, now: float) -> bool:
        """
        Report whether the entry is still within its TTL.

        Args:
            now (float): The current time.

        Returns:
            bool: True if the entry can be served as a normal hit.
        """
        return self.age(now) < self.ttl

    def is_servable_stale(self, now: float, stale_seconds: float) -> bool:
        """
        Report whether an expired entry may still be served during an upstream block.

        Negative entries are never served stale: a cached 404 is only trustworthy while fresh.

        Args:
            now (float): The current time.
            stale_seconds (float): The stale window beyond the TTL.

        Returns:
            bool: True if the entry can be served with an X-Cache: STALE marker.
        """
        return not self.is_error and self.age(now) < self.ttl + stale_seconds


class ResponseCache:
    """
    Bounded, thread-safe cache of endpoint responses with a stale-serving window.

    Freshness is tracked per entry rather than by evicting on expiry, because expired entries are
    exactly what gets served when Transfermarkt blocks a scrape. Entries are dropped only when they
    fall out of the stale window or are evicted by the LRU bound.

    Args:
        maxsize (int): Maximum number of entries retained.
        stale_seconds (float): How long past its TTL an entry stays servable.
        clock (Callable[[], float]): Time source, injectable for tests.
    """

    def __init__(
        self,
        maxsize: Optional[int] = None,
        stale_seconds: Optional[float] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the ResponseCache."""
        self._maxsize = maxsize
        self._stale_seconds = stale_seconds
        self._clock = clock
        self._store: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._lock = threading.Lock()
        self._keylocks: dict = {}
        self._keylocks_lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.stale_served = 0

    @property
    def maxsize(self) -> int:
        """
        Return the configured entry ceiling.

        Returns:
            int: Maximum number of retained entries.
        """
        return settings.CACHE_MAX_ENTRIES if self._maxsize is None else self._maxsize

    @property
    def stale_seconds(self) -> float:
        """
        Return the configured stale window.

        Returns:
            float: Seconds past TTL that an entry stays servable.
        """
        return settings.CACHE_STALE_SECONDS if self._stale_seconds is None else self._stale_seconds

    def now(self) -> float:
        """
        Return the current time from the injected clock.

        Returns:
            float: Current time in seconds.
        """
        return self._clock()

    def get(self, key: str) -> Optional[CacheEntry]:
        """
        Look up an entry, dropping it if it has fallen out of the stale window.

        The returned entry may be expired; callers decide whether to serve it fresh or stale.

        Args:
            key (str): The cache key.

        Returns:
            Optional[CacheEntry]: The entry, or None if absent or fully expired.
        """
        now = self.now()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            retention = entry.ttl if entry.is_error else entry.ttl + self.stale_seconds
            if entry.age(now) >= retention:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry

    def set(self, key: str, value: Any, ttl: float, is_error: bool = False) -> CacheEntry:
        """
        Store a value, evicting the least recently used entry if the cache is full.

        Args:
            key (str): The cache key.
            value (Any): The payload, or an HTTPException for a negative entry.
            ttl (float): Seconds the entry stays fresh.
            is_error (bool): True when storing a negative result.

        Returns:
            CacheEntry: The stored entry.
        """
        entry = CacheEntry(
            value=value,
            stored_at=self.now(),
            ttl=ttl,
            is_error=is_error,
            etag="" if is_error else make_etag(value),
        )
        with self._lock:
            self._store[key] = entry
            self._store.move_to_end(key)
            while len(self._store) > self.maxsize:
                self._store.popitem(last=False)
        return entry

    @contextmanager
    def single_flight(self, key: str) -> Iterator[None]:
        """
        Serialize concurrent misses for the same key so only one scrape is made.

        The per-key lock is reference counted and removed once the last waiter releases it, so the
        lock table cannot grow without bound.

        Args:
            key (str): The cache key being filled.

        Yields:
            None: With the per-key lock held.
        """
        with self._keylocks_lock:
            lock, waiters = self._keylocks.get(key, (threading.Lock(), 0))
            self._keylocks[key] = (lock, waiters + 1)

        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._keylocks_lock:
                held_lock, waiters = self._keylocks[key]
                if waiters <= 1:
                    del self._keylocks[key]
                else:
                    self._keylocks[key] = (held_lock, waiters - 1)

    def clear(self) -> None:
        """Drop every entry and reset counters."""
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            self.stale_served = 0

    def stats(self) -> dict:
        """
        Return a snapshot of cache counters, for the /health endpoint.

        Returns:
            dict: Entry count, ceiling, and hit/miss/stale tallies.
        """
        with self._lock:
            entries = len(self._store)
        total = self.hits + self.misses
        return {
            "entries": entries,
            "maxEntries": self.maxsize,
            "hits": self.hits,
            "misses": self.misses,
            "staleServed": self.stale_served,
            "hitRate": round(self.hits / total, 3) if total else None,
        }


cache = ResponseCache()


def stamp_scrape_time(value: Any) -> Any:
    """
    Record when a payload was actually scraped, so `updatedAt` survives caching.

    The schemas default `updatedAt` to `datetime.now` at serialization time, which would make every
    cache hit claim it was updated just now. Stamping the value before it is stored pins the field
    to the moment the data really came off Transfermarkt.

    Args:
        value (Any): The payload returned by an endpoint.

    Returns:
        Any: The payload, stamped in place when it is a dict.
    """
    if isinstance(value, dict) and "updatedAt" not in value:
        value["updatedAt"] = datetime.now()
    return value


def make_etag(value: Any) -> str:
    """
    Derive a weak ETag from a response payload.

    Args:
        value (Any): The payload to fingerprint.

    Returns:
        str: A weak ETag, or an empty string if the payload is not serializable.
    """
    try:
        encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return f'W/"{hashlib.sha256(encoded).hexdigest()[:32]}"'


def build_key(namespace: str, params: dict) -> str:
    """
    Build a stable cache key from an endpoint's bound arguments.

    Args:
        namespace (str): Identifier for the endpoint.
        params (dict): The endpoint's arguments, excluding the injected Response.

    Returns:
        str: The cache key, hashed when the parameters are long or awkward.
    """
    rendered = "|".join(f"{k}={params[k]!r}" for k in sorted(params))
    if len(rendered) > 200 or not rendered.isascii():
        rendered = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:32]
    return f"{namespace}:{rendered}"


def apply_headers(response: Optional[Response], entry: CacheEntry, status: str, now: float) -> None:
    """
    Annotate the outgoing response with cache metadata.

    Args:
        response (Optional[Response]): The response to annotate; ignored if None.
        entry (CacheEntry): The entry that produced the payload.
        status (str): One of HIT, MISS, or STALE.
        now (float): The current time.
    """
    if response is None:
        return

    response.headers["X-Cache"] = status
    if entry.etag:
        response.headers["ETag"] = entry.etag

    age = int(entry.age(now))
    if status in ("HIT", "STALE"):
        response.headers["Age"] = str(age)

    remaining = int(entry.ttl - entry.age(now))
    if remaining > 0:
        response.headers["Cache-Control"] = f"public, max-age={remaining}"
    else:
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"

    if status == "STALE":
        response.headers["Warning"] = '110 - "Response is Stale"'


def cached(namespace: str, ttl: str = "short", archive_param: Optional[str] = None) -> Callable:
    """
    Cache an endpoint's response, serving stale data when Transfermarkt blocks a scrape.

    Concurrent misses for the same key are coalesced into a single scrape, genuine 404s are cached
    briefly so bad ids are not re-scraped, and a bot challenge falls back to an expired entry rather
    than surfacing as an error.

    Args:
        namespace (str): Identifier for the endpoint, used as the key prefix.
        ttl (str): Name of the TTL tier from TTL_TIERS.
        archive_param (Optional[str]): Name of a season parameter; when it names a completed season
            the archive tier is used instead, since past-season data never changes.

    Returns:
        Callable: The decorator.
    """

    def decorator(fn: Callable) -> Callable:
        """
        Wrap a single endpoint function.

        Args:
            fn (Callable): The endpoint function.

        Returns:
            Callable: The caching wrapper.
        """
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            """
            Serve the endpoint from cache when possible, otherwise scrape and store.

            Returns:
                Any: The endpoint payload.
            """
            if not settings.CACHE_ENABLE:
                return fn(*args, **kwargs)

            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            params = {k: v for k, v in bound.arguments.items() if k != "response"}
            response = bound.arguments.get("response")
            key = build_key(namespace, params)

            resolved_ttl = TTL_TIERS[ttl]()
            if archive_param and is_past_season(params.get(archive_param)):
                resolved_ttl = TTL_TIERS["archive"]()

            served = _serve_if_fresh(key, response)
            if served is not _MISS:
                return served

            # Only one caller scrapes a given key; the rest wait here and take the result.
            with cache.single_flight(key):
                served = _serve_if_fresh(key, response)
                if served is not _MISS:
                    return served

                try:
                    value = fn(*args, **kwargs)
                except BotChallengeError as challenge:
                    return _serve_stale_or_fail(key, response, challenge)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        cache.set(key, exc, settings.CACHE_NEGATIVE_TTL, is_error=True)
                    raise

                cache.misses += 1
                entry = cache.set(key, stamp_scrape_time(value), resolved_ttl)
                apply_headers(response, entry, "MISS", cache.now())
                return value

        return wrapper

    return decorator


class _Miss:
    """Sentinel type distinguishing "no cached result" from a cached value of None."""


_MISS = _Miss()


def _serve_if_fresh(key: str, response: Optional[Response]) -> Any:
    """
    Return a fresh cached result if one exists, re-raising cached 404s.

    Args:
        key (str): The cache key.
        response (Optional[Response]): The response to annotate on a hit.

    Returns:
        Any: The cached payload, or the _MISS sentinel.
    """
    entry = cache.get(key)
    if entry is None or not entry.is_fresh(cache.now()):
        return _MISS

    cache.hits += 1
    if entry.is_error:
        raise entry.value
    apply_headers(response, entry, "HIT", cache.now())
    return entry.value


def _serve_stale_or_fail(key: str, response: Optional[Response], challenge: BotChallengeError) -> Any:
    """
    Fall back to expired cached data after a bot challenge, or fail with a 503.

    Args:
        key (str): The cache key.
        response (Optional[Response]): The response to annotate when serving stale.
        challenge (BotChallengeError): The challenge that blocked the scrape.

    Returns:
        Any: The stale payload.

    Raises:
        HTTPException: 503 when no stale entry is available.
    """
    now = cache.now()
    entry = cache.get(key)
    if entry is not None and entry.is_servable_stale(now, cache.stale_seconds):
        cache.stale_served += 1
        logger.warning("Serving stale response for %s (age %ss) after bot challenge", key, int(entry.age(now)))
        apply_headers(response, entry, "STALE", now)
        return entry.value

    retry_after = bot_breaker.retry_after or settings.BOT_BREAKER_COOLDOWN
    logger.warning("Bot challenge for %s with no stale entry available", key)
    raise HTTPException(
        status_code=503,
        detail=f"Upstream temporarily unavailable (bot challenge) for url: {challenge.url}",
        headers={"Retry-After": str(retry_after)},
    )
