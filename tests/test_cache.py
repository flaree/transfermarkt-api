import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from app.main import conditional_get
from app.services.base import is_bot_challenge
from app.settings import settings
from app.utils.breaker import CircuitBreaker, bot_breaker
from app.utils.cache import CacheEntry, ResponseCache, build_key, cache, cached, is_past_season


class FakeClock:
    """A manually advanced time source, so TTL behaviour can be tested without sleeping."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        """Initialize the FakeClock."""
        self.now = start

    def __call__(self) -> float:
        """
        Return the current fake time.

        Returns:
            float: The current time.
        """
        return self.now

    def advance(self, seconds: float) -> None:
        """
        Move the clock forward.

        Args:
            seconds (float): How far to advance.
        """
        self.now += seconds


@pytest.fixture
def clock():
    """
    Install a fake clock on the global cache and restore the real one afterwards.

    Returns:
        FakeClock: The installed clock.
    """
    fake = FakeClock()
    original = cache._clock
    cache._clock = fake
    cache.clear()
    yield fake
    cache._clock = original
    cache.clear()


@pytest.fixture
def breaker():
    """
    Reset the shared bot breaker around a test.

    Returns:
        CircuitBreaker: The shared breaker.
    """
    bot_breaker.reset()
    yield bot_breaker
    bot_breaker.reset()


def make_client(endpoint):
    """
    Build a minimal app exposing one endpoint plus the conditional-GET middleware.

    Args:
        endpoint (Callable): The endpoint function to mount at /item/{item_id}.

    Returns:
        TestClient: A client for the app.
    """
    app = FastAPI()
    app.middleware("http")(conditional_get)
    app.get("/item/{item_id}")(endpoint)
    return TestClient(app)


class TestCacheEntry:
    """Freshness and stale-window arithmetic on a single entry."""

    def test_fresh_within_ttl(self):
        """An entry is fresh until its TTL elapses."""
        entry = CacheEntry(value={"a": 1}, stored_at=100.0, ttl=60)
        assert entry.is_fresh(159.0)
        assert not entry.is_fresh(160.0)

    def test_servable_stale_within_window(self):
        """An expired entry stays servable through the stale window, then stops."""
        entry = CacheEntry(value={"a": 1}, stored_at=100.0, ttl=60)
        assert entry.is_servable_stale(300.0, stale_seconds=600)
        assert not entry.is_servable_stale(800.0, stale_seconds=600)

    def test_error_entries_are_never_served_stale(self):
        """A cached 404 is only trustworthy while fresh."""
        entry = CacheEntry(value=HTTPException(404), stored_at=100.0, ttl=60, is_error=True)
        assert not entry.is_servable_stale(120.0, stale_seconds=600)


class TestResponseCache:
    """Storage, retention, eviction, and coalescing behaviour of the store itself."""

    def test_get_returns_expired_entry_for_stale_use(self):
        """Expired entries survive lookup so they can be served during a block."""
        fake = FakeClock()
        store = ResponseCache(maxsize=10, stale_seconds=600, clock=fake)
        store.set("k", {"v": 1}, ttl=60)
        fake.advance(120)

        entry = store.get("k")
        assert entry is not None
        assert not entry.is_fresh(fake.now)

    def test_get_drops_entry_past_stale_window(self):
        """Entries are discarded once they fall out of the stale window."""
        fake = FakeClock()
        store = ResponseCache(maxsize=10, stale_seconds=600, clock=fake)
        store.set("k", {"v": 1}, ttl=60)
        fake.advance(700)

        assert store.get("k") is None

    def test_negative_entries_expire_at_ttl(self):
        """Error entries get no stale window at all."""
        fake = FakeClock()
        store = ResponseCache(maxsize=10, stale_seconds=600, clock=fake)
        store.set("k", HTTPException(404), ttl=60, is_error=True)
        fake.advance(61)

        assert store.get("k") is None

    def test_lru_eviction_respects_maxsize(self):
        """The store never grows past its ceiling, dropping least-recently-used entries."""
        store = ResponseCache(maxsize=3, stale_seconds=600)
        for i in range(5):
            store.set(f"k{i}", {"v": i}, ttl=60)

        assert store.stats()["entries"] == 3
        assert store.get("k0") is None
        assert store.get("k4") is not None

    def test_lru_eviction_keeps_recently_read_entries(self):
        """Reading an entry protects it from the next eviction."""
        store = ResponseCache(maxsize=2, stale_seconds=600)
        store.set("a", {"v": 1}, ttl=60)
        store.set("b", {"v": 2}, ttl=60)
        store.get("a")
        store.set("c", {"v": 3}, ttl=60)

        assert store.get("a") is not None
        assert store.get("b") is None

    def test_single_flight_lock_table_does_not_leak(self):
        """Per-key locks are reference counted and removed once released."""
        store = ResponseCache(maxsize=10, stale_seconds=600)
        with store.single_flight("k"):
            assert "k" in store._keylocks
        assert store._keylocks == {}


class TestKeyBuilding:
    """Cache key construction."""

    def test_distinct_params_produce_distinct_keys(self):
        """Different arguments must not collide."""
        assert build_key("ns", {"id": "1"}) != build_key("ns", {"id": "2"})

    def test_key_is_order_independent(self):
        """Key building sorts parameters, so dict ordering is irrelevant."""
        assert build_key("ns", {"a": 1, "b": 2}) == build_key("ns", {"b": 2, "a": 1})

    def test_long_and_unicode_params_are_hashed(self):
        """Oversized or non-ascii parameters are hashed to keep keys bounded."""
        key = build_key("ns", {"q": "Mbappé"})
        assert key.startswith("ns:")
        assert "Mbappé" not in key


class TestSeasonTiering:
    """Past-season detection driving the archive TTL."""

    def test_none_is_current_season(self):
        """An omitted season means the current one."""
        assert not is_past_season(None)

    def test_old_season_is_past(self):
        """A clearly historical season is archivable."""
        assert is_past_season(2015)
        assert is_past_season("2015")

    def test_future_season_is_not_past(self):
        """A future season is not archivable."""
        assert not is_past_season(2999)

    def test_garbage_is_not_past(self):
        """Unparseable season ids fall back to the normal TTL."""
        assert not is_past_season("not-a-season")


class TestCachedEndpoint:
    """End-to-end decorator behaviour through a real request cycle."""

    def test_miss_then_hit(self, clock):
        """A second identical request is served from cache without re-scraping."""
        service = Mock(return_value={"id": "1"})

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)

        first = client.get("/item/1")
        second = client.get("/item/1")

        assert first.headers["x-cache"] == "MISS"
        assert second.headers["x-cache"] == "HIT"
        assert second.json()["id"] == "1"
        assert service.call_count == 1

    def test_distinct_params_are_cached_separately(self, clock):
        """Two different ids each get their own entry."""
        service = Mock(side_effect=lambda item_id: {"id": item_id})

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        client.get("/item/2")

        assert service.call_count == 2

    def test_expiry_triggers_rescrape(self, clock):
        """Once the TTL lapses the endpoint is called again."""
        service = Mock(return_value={"id": "1"})

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        clock.advance(settings.CACHE_TTL_SHORT + 1)
        response = client.get("/item/1")

        assert service.call_count == 2
        assert response.headers["x-cache"] == "MISS"

    def test_updated_at_is_pinned_to_scrape_time(self, clock):
        """
        A cache hit must not claim the data was refreshed just now.

        The schemas default updatedAt to datetime.now at serialization time, so without an explicit
        stamp every hit would report itself as freshly scraped.
        """

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return {"id": item_id}

        client = make_client(endpoint)
        first = client.get("/item/1").json()
        second = client.get("/item/1").json()

        assert "updatedAt" in first
        assert first["updatedAt"] == second["updatedAt"]

    def test_age_and_cache_control_headers(self, clock):
        """Hits report their age and the remaining freshness budget."""

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return {"id": item_id}

        client = make_client(endpoint)
        client.get("/item/1")
        clock.advance(120)
        response = client.get("/item/1")

        assert response.headers["age"] == "120"
        assert response.headers["cache-control"] == f"public, max-age={settings.CACHE_TTL_SHORT - 120}"

    def test_disabled_cache_always_calls_through(self, clock, monkeypatch):
        """CACHE_ENABLE=false bypasses the cache entirely."""
        monkeypatch.setattr(settings, "CACHE_ENABLE", False)
        service = Mock(return_value={"id": "1"})

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        client.get("/item/1")

        assert service.call_count == 2


class TestBotChallengeFallback:
    """What callers see when Transfermarkt blocks a scrape."""

    def test_stale_served_on_challenge(self, clock, breaker):
        """An expired entry is returned rather than an error when the scrape is blocked."""
        from app.utils.exceptions import BotChallengeError

        service = Mock(side_effect=[{"id": "1"}, BotChallengeError("http://x", 202)])

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        clock.advance(settings.CACHE_TTL_SHORT + 60)
        response = client.get("/item/1")

        assert response.status_code == 200
        assert response.headers["x-cache"] == "STALE"
        assert response.json()["id"] == "1"
        assert int(response.headers["age"]) == settings.CACHE_TTL_SHORT + 60

    def test_503_when_no_stale_entry(self, clock, breaker):
        """With nothing cached, a challenge surfaces as a 503 with Retry-After."""
        from app.utils.exceptions import BotChallengeError

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            raise BotChallengeError("http://x", 202)

        client = make_client(endpoint)
        response = client.get("/item/1")

        assert response.status_code == 503
        assert int(response.headers["retry-after"]) > 0

    def test_stale_expires_eventually(self, clock, breaker):
        """Past the stale window the fallback is gone and the caller gets a 503."""
        from app.utils.exceptions import BotChallengeError

        service = Mock(side_effect=[{"id": "1"}, BotChallengeError("http://x", 202)])

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        clock.advance(settings.CACHE_TTL_SHORT + settings.CACHE_STALE_SECONDS + 1)

        assert client.get("/item/1").status_code == 503


class TestNegativeCaching:
    """Genuine 404s are remembered briefly so bad ids are not re-scraped."""

    def test_404_is_cached(self, clock):
        """A repeated request for a missing id does not hit the network again."""
        service = Mock(side_effect=HTTPException(status_code=404, detail="Invalid request"))

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        first = client.get("/item/nope")
        second = client.get("/item/nope")

        assert first.status_code == 404
        assert second.status_code == 404
        assert service.call_count == 1

    def test_404_cache_expires_quickly(self, clock):
        """The negative entry lapses after CACHE_NEGATIVE_TTL."""
        service = Mock(side_effect=HTTPException(status_code=404, detail="Invalid request"))

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/nope")
        clock.advance(settings.CACHE_NEGATIVE_TTL + 1)
        client.get("/item/nope")

        assert service.call_count == 2

    def test_500_is_not_cached(self, clock):
        """Server errors are transient and must not be memoized."""
        service = Mock(side_effect=HTTPException(status_code=500, detail="boom"))

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return service(item_id)

        client = make_client(endpoint)
        client.get("/item/1")
        client.get("/item/1")

        assert service.call_count == 2


class TestSingleFlight:
    """Concurrent misses for one key collapse into a single scrape."""

    def test_concurrent_misses_scrape_once(self, clock):
        """Ten simultaneous callers produce one upstream request."""
        calls = []
        started = threading.Event()

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            calls.append(item_id)
            started.wait(timeout=1)
            return {"id": item_id}

        def call():
            """
            Invoke the decorated endpoint directly.

            Returns:
                dict: The endpoint payload.
            """
            return endpoint(response=Response(), item_id="1")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(call) for _ in range(10)]
            started.set()
            results = [f.result() for f in futures]

        assert len(calls) == 1
        assert all(r["id"] == "1" for r in results)


class TestConditionalGet:
    """ETag revalidation."""

    def test_matching_etag_returns_304(self, clock):
        """A client echoing the ETag gets a bodyless 304."""

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return {"id": item_id}

        client = make_client(endpoint)
        first = client.get("/item/1")
        etag = first.headers["etag"]

        second = client.get("/item/1", headers={"If-None-Match": etag})

        assert second.status_code == 304
        assert second.content == b""

    def test_mismatched_etag_returns_body(self, clock):
        """A stale validator gets the full response."""

        @cached(namespace="test.item", ttl="short")
        def endpoint(response: Response, item_id: str):
            """Test endpoint."""
            return {"id": item_id}

        client = make_client(endpoint)
        client.get("/item/1")
        response = client.get("/item/1", headers={"If-None-Match": 'W/"nonsense"'})

        assert response.status_code == 200
        assert response.json()["id"] == "1"


class TestCircuitBreaker:
    """Breaker state transitions."""

    def test_opens_after_threshold(self):
        """Consecutive challenges trip the circuit."""
        fake = FakeClock()
        cb = CircuitBreaker(threshold=3, cooldown=60, clock=fake)

        for _ in range(2):
            cb.record_failure()
        assert cb.allow()

        cb.record_failure()
        assert not cb.allow()
        assert cb.is_open

    def test_success_resets_failures(self):
        """A successful fetch clears accumulated failures."""
        fake = FakeClock()
        cb = CircuitBreaker(threshold=3, cooldown=60, clock=fake)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()

        assert cb.allow()

    def test_trial_request_after_cooldown(self):
        """Once the cooldown elapses a single trial request is permitted."""
        fake = FakeClock()
        cb = CircuitBreaker(threshold=2, cooldown=60, clock=fake)
        cb.record_failure()
        cb.record_failure()
        assert not cb.allow()

        fake.advance(61)
        assert cb.allow()

    def test_failed_trial_reopens_immediately(self):
        """A challenge on the trial request re-opens the circuit at once."""
        fake = FakeClock()
        cb = CircuitBreaker(threshold=2, cooldown=60, clock=fake)
        cb.record_failure()
        cb.record_failure()
        fake.advance(61)
        cb.allow()

        cb.record_failure()
        assert not cb.allow()

    def test_retry_after_counts_down(self):
        """Retry-After reflects the remaining cooldown."""
        fake = FakeClock()
        cb = CircuitBreaker(threshold=1, cooldown=60, clock=fake)
        cb.record_failure()
        assert cb.retry_after == 60

        fake.advance(30)
        assert cb.retry_after == 30


class TestChallengeDetection:
    """Identifying an anti-bot interstitial from the raw response."""

    @staticmethod
    def fake_response(status_code: int, body: bytes = b"", headers: dict = None):
        """
        Build a minimal stand-in for a requests Response.

        Args:
            status_code (int): The status code.
            body (bytes): The response body.
            headers (dict): Response headers.

        Returns:
            Mock: The fake response.
        """
        response = Mock()
        response.status_code = status_code
        response.content = body
        response.text = body.decode("utf-8", errors="ignore")
        response.headers = headers or {}
        return response

    def test_202_is_always_a_challenge(self):
        """Transfermarkt never legitimately answers these GETs with 202."""
        assert is_bot_challenge(self.fake_response(202))

    def test_large_200_is_not_inspected(self):
        """A full-size page is content, not a challenge."""
        assert not is_bot_challenge(self.fake_response(200, b"x" * 25_000))

    def test_small_200_with_marker_is_a_challenge(self):
        """A short interstitial served with a 200 is still a block."""
        body = b"<html><script src='https://geo.captcha-delivery.com/c.js'></script></html>"
        assert is_bot_challenge(self.fake_response(200, body))

    def test_403_with_datadome_cookie_is_a_challenge(self):
        """A hard block is identified from the Set-Cookie header."""
        response = self.fake_response(403, b"blocked", {"Set-Cookie": "datadome=abc; Path=/"})
        assert is_bot_challenge(response)

    def test_plain_404_is_not_a_challenge(self):
        """A genuine missing resource must stay a 404."""
        assert not is_bot_challenge(self.fake_response(404, b"not found"))
