import pytest
from schema import Regex

from app.utils.breaker import bot_breaker
from app.utils.cache import cache


@pytest.fixture(autouse=True)
def isolate_cache():
    """Stop cached responses and breaker state from leaking between tests."""
    cache.clear()
    bot_breaker.reset()
    yield
    cache.clear()
    bot_breaker.reset()


@pytest.fixture
def len_greater_than_0():
    return lambda x: len(x) > 0


@pytest.fixture
def len_equal_to_0():
    return lambda x: len(x) == 0


@pytest.fixture
def regex_club_url():
    return Regex(r"^/\w.+/startseite/verein/\d+$")


@pytest.fixture
def regex_date_mmm_dd_yyyy():
    return Regex(r"^(\w+\s\d+,\s\d+)|(-)$")


@pytest.fixture
def regex_market_value():
    return Regex(r"^(€\d+\.\d+.(m|bn))|(€\d+.k)|(-)$")


@pytest.fixture
def regex_value_variation():
    return Regex(r"^(\+|-)?€(\+|-)?(\d.+)(k|m)$")


@pytest.fixture
def regex_integer():
    return Regex(r"^(\d+|-)$")


@pytest.fixture
def regex_height():
    return Regex(r"^(\d+,\d+m)|(m)$")
