import logging
import threading
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from lxml import etree
from requests import Response, TooManyRedirects

from app.settings import settings
from app.utils.breaker import bot_breaker
from app.utils.exceptions import BotChallengeError
from app.utils.utils import trim
from app.utils.xpath import Pagination

logger = logging.getLogger(__name__)

# Headers for a page navigation. Transfermarkt's anti-bot layer fingerprints the whole header set,
# not just the User-Agent, so these mirror what a current Chrome actually sends. Accept-Encoding is
# deliberately omitted: requests advertises only the codecs it can actually decode.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
        "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# The /ceapi/ endpoints are fetched by the page's own JavaScript. Announcing them as a top-level
# document navigation is an obvious inconsistency, so they get XHR-shaped headers instead.
XHR_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

# Substrings identifying a DataDome interstitial rather than real content.
CHALLENGE_MARKERS = ("datadome", "captcha-delivery.com", "geo.captcha-delivery")

_session: Optional[requests.Session] = None
_session_lock = threading.Lock()


def get_session() -> requests.Session:
    """
    Return the process-wide requests Session, creating it on first use.

    A single Session is what makes the anti-bot clearance cookie persist: `requests.get` builds a
    throwaway Session per call and discards its cookie jar, so every request re-enters the challenge
    funnel as a first-time visitor.

    Returns:
        requests.Session: The shared session, with browser-shaped default headers applied.
    """
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                session = requests.Session()
                session.headers.update(BROWSER_HEADERS)
                _session = session
    return _session


def reset_session() -> None:
    """Drop the shared session and its cookie jar (used by tests, and after a hard block)."""
    global _session
    with _session_lock:
        if _session is not None:
            _session.close()
        _session = None


def is_bot_challenge(response: Response) -> bool:
    """
    Determine whether a response is an anti-bot interstitial rather than the requested content.

    Args:
        response (Response): The HTTP response to inspect.

    Returns:
        bool: True if the response is a challenge page.
    """
    # Transfermarkt never legitimately answers these GETs with 202.
    if response.status_code == 202:
        return True

    # Only inspect the body when the response is already suspect: a challenge arrives either with a
    # blocking status or as an interstitial far smaller than a real Transfermarkt page. This keeps
    # the common path from decoding hundreds of KB of HTML just to scan it.
    if response.status_code not in (403, 429) and len(response.content) >= 20_000:
        return False

    haystack = " ".join(
        [
            response.headers.get("Set-Cookie", ""),
            response.headers.get("Server", ""),
            response.text[:4000],
        ],
    ).lower()
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


@dataclass
class TransfermarktBase:
    """
    Base class for making HTTP requests to Transfermarkt and extracting data from the web pages.

    Args:
        URL (str): The URL for the web page to be fetched.
    Attributes:
        page (ElementTree): The parsed web page content.
        response (dict): A dictionary to store the response data.
    """

    URL: str
    page: ElementTree = field(default_factory=lambda: None, init=False)
    response: dict = field(default_factory=lambda: {}, init=False)

    def make_request(self, url: Optional[str] = None) -> Response:
        """
        Make an HTTP GET request to the specified URL.

        Args:
            url (str, optional): The URL to make the request to. If not provided, the class's URL
                attribute will be used.

        Returns:
            Response: An HTTP Response object containing the server's response to the request.

        Raises:
            BotChallengeError: If the anti-bot layer served a challenge instead of the content, or
                if the circuit breaker is open after repeated challenges.
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        url = self.URL if not url else url

        # Fail fast while the breaker is open so the caller can fall back to stale data instead of
        # spending a round trip on a request that is going to be challenged anyway.
        if not bot_breaker.allow():
            logger.warning("Circuit open, skipping request to %s", url)
            raise BotChallengeError(url=url, status_code=202)

        headers = dict(XHR_HEADERS) if "/ceapi/" in url else {}
        try:
            proxy_url = settings.PROXY_URL
            proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
            response: Response = get_session().get(
                url,
                headers=headers,
                proxies=proxies,
                timeout=10,
            )
        except TooManyRedirects:
            raise HTTPException(status_code=404, detail=f"Not found for url: {url}")
        except requests.exceptions.ConnectionError:
            raise HTTPException(status_code=500, detail=f"Connection error for url: {url}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error for url: {url}. {e}")

        if is_bot_challenge(response):
            bot_breaker.record_failure()
            logger.warning("Bot challenge (%s) for url: %s", response.status_code, url)
            raise BotChallengeError(url=url, status_code=response.status_code)

        # Getting a real answer means the anti-bot layer let us through, whatever the status is.
        bot_breaker.record_success()

        if 400 <= response.status_code < 500:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Client Error. {response.reason} for url: {url}",
            )
        elif 500 <= response.status_code < 600:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Server Error. {response.reason} for url: {url}",
            )
        logger.info("Fetched %s (%s)", url, response.status_code)
        return response

    def request_url_bsoup(self) -> BeautifulSoup:
        """
        Fetch the web page content and parse it using BeautifulSoup.

        Returns:
            BeautifulSoup: A BeautifulSoup object representing the parsed web page content.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        response: Response = self.make_request()
        return BeautifulSoup(markup=response.content, features="html.parser")

    @staticmethod
    def convert_bsoup_to_page(bsoup: BeautifulSoup) -> ElementTree:
        """
        Convert a BeautifulSoup object to an ElementTree.

        Args:
            bsoup (BeautifulSoup): The BeautifulSoup object representing the parsed web page content.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further processing.
        """
        return etree.HTML(str(bsoup))

    def request_url_page(self) -> ElementTree:
        """
        Fetch the web page content, parse it using BeautifulSoup, and convert it to an ElementTree.

        Returns:
            ElementTree: An ElementTree representing the parsed web page content for further
                processing.

        Raises:
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        bsoup: BeautifulSoup = self.request_url_bsoup()
        page = self.convert_bsoup_to_page(bsoup=bsoup)
        if page is None:
            raise HTTPException(
                status_code=502,
                detail=f"Received an empty or unparseable response from url: {self.URL}",
            )
        return page

    def raise_exception_if_not_found(self, xpath: str):
        """
        Raise an exception if the specified XPath does not yield any results on the web page.

        Args:
            xpath (str): The XPath expression to query elements on the page.

        Raises:
            HTTPException: If the specified XPath query does not yield any results, indicating an invalid request.
        """
        if not self.get_text_by_xpath(xpath):
            raise HTTPException(status_code=404, detail=f"Invalid request (url: {self.URL})")

    def get_list_by_xpath(self, xpath: str, remove_empty: Optional[bool] = True) -> Optional[list]:
        """
        Extract a list of elements from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            remove_empty (bool, optional): If True, remove empty or whitespace-only elements from
                the list. Default is True.

        Returns:
            Optional[list]: A list of elements extracted from the web page based on the XPath query.
                If remove_empty is True, empty or whitespace-only elements are filtered out.
        """
        elements: list = self.page.xpath(xpath)
        if remove_empty:
            elements_valid: list = [trim(e) for e in elements if trim(e)]
        else:
            elements_valid: list = [trim(e) for e in elements]
        return elements_valid or []

    def get_text_by_xpath(
        self,
        xpath: str,
        pos: int = 0,
        iloc: Optional[int] = None,
        iloc_from: Optional[int] = None,
        iloc_to: Optional[int] = None,
        join_str: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract text content from the web page using the specified XPath expression.

        Args:
            xpath (str): The XPath expression to query elements on the page.
            pos (int, optional): Index of the element to extract if multiple elements match the
                XPath. Default is 0.
            iloc (int, optional): Extract a single element by index, used as an alternative to 'pos'.
            iloc_from (int, optional): Extract a range of elements starting from the specified
                index (inclusive).
            iloc_to (int, optional): Extract a range of elements up to the specified
                index (exclusive).
            join_str (str, optional): If provided, join multiple text elements into a single string
                using this separator.

        Returns:
            Optional[str]: The extracted text content from the web page based on the XPath query and
                optional parameters. If no matching element is found, None is returned.
        """
        element = self.page.xpath(xpath)

        if not element:
            return None

        if isinstance(element, list):
            element = [trim(e) for e in element if trim(e)]

        if isinstance(iloc, int):
            element = element[iloc]

        if isinstance(iloc_from, int) and isinstance(iloc_to, int):
            element = element[iloc_from:iloc_to]

        if isinstance(iloc_to, int):
            element = element[:iloc_to]

        if isinstance(iloc_from, int):
            element = element[iloc_from:]

        if isinstance(join_str, str):
            return join_str.join([trim(e) for e in element])

        try:
            return trim(element[pos])
        except IndexError:
            return None

    def get_last_page_number(self, xpath_base: str = "") -> int:
        """
        Retrieve the last page number for a paginated result based on the provided base XPath.

        Args:
            xpath_base (str): The base XPath for extracting page number information.

        Returns:
            int: The last page number for search results. Returns 1 if no page numbers are found.
        """

        for xpath in [Pagination.PAGE_NUMBER_LAST, Pagination.PAGE_NUMBER_ACTIVE]:
            url_page = self.get_text_by_xpath(xpath_base + xpath)
            if url_page:
                return int(url_page.split("=")[-1].split("/")[-1])
        return 1
