from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from lxml import etree
from requests import Response, TooManyRedirects
import time
import httpx

from app.utils.utils import trim
from app.utils.xpath import Pagination


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
            HTTPException: If there are too many redirects, or if the server returns a client or
                server error status code.
        """
        url = self.URL if not url else url
        try:
            proxies = ["92.114.157.221:4145", "196.0.111.194:48009", "5.75.168.247:8046", "193.243.154.146:4145", "134.249.128.111:1080", "62.4.37.104:60606", "31.43.194.184:1080", "103.184.67.37:1080", "77.65.50.118:34159", "36.94.119.218:4145", "37.52.13.164:5678", "117.102.115.154:4153", "8.218.227.50:1011", "178.49.215.7:1080", "182.52.70.117:4145", "168.253.92.93:10808", "1.179.172.45:31225", "141.94.195.25:22563", "185.30.43.65:60606", "110.77.135.70:4145", "91.126.132.83:80", "72.49.49.11:31034", "128.199.37.92:1080", "91.187.121.211:2080", "72.37.216.68:4145", "80.78.73.120:65530", "72.205.0.67:4145", "199.127.176.139:64312", "216.68.128.121:4145", "192.111.139.163:19404", "203.188.245.98:52837", "77.241.20.215:55915", "176.241.82.149:5678", "188.163.170.130:35578", "123.136.24.161:1080", "98.182.171.161:4145", "95.182.78.6:5678", "199.116.112.6:4145", "14.241.241.185:4145", "68.71.252.38:4145", "192.252.210.233:4145", "72.206.74.126:4145", "68.71.245.206:4145", "192.252.214.20:15864", "199.58.185.9:4145", "192.111.137.35:4145", "163.47.174.47:1080", "98.181.137.80:4145", "192.111.137.34:18765", "72.195.34.60:27391", "68.183.143.134:80", "104.236.171.128:41047", "103.53.110.45:10801", "185.32.4.110:4153", "192.252.211.197:14921", "184.170.245.148:4145", "198.0.198.132:54321", "2.115.212.62:48293", "31.211.142.115:8192", "138.68.60.8:1080", "72.214.108.67:4145", "198.8.94.174:39078", "142.54.237.38:4145", "167.99.236.14:80", "142.54.231.38:4145", "103.168.246.3:4153", "74.119.144.60:4145", "24.249.199.12:4145", "192.252.208.70:14282", "200.48.35.122:999", "192.111.130.2:4145", "1.20.227.66:4145", "46.8.60.2:1080", "192.252.215.5:16137", "67.201.39.14:4145", "95.173.218.77:8081", "95.173.218.73:8081", "192.252.220.89:4145", "192.252.211.193:4145", "34.48.171.130:33080", "142.54.228.193:4145", "194.182.80.201:3128", "107.174.82.16:21080", "47.252.29.28:11222", "209.97.150.167:8080", "34.45.207.111:9080", "103.217.216.65:8181", "200.188.112.140:999", "89.110.80.195:10149", "139.99.237.62:80", "95.173.218.69:8082", "43.224.116.222:1120", "200.48.35.123:999", "198.49.68.80:80", "200.48.35.125:999", "219.65.73.81:80", "80.74.54.148:3128", "216.229.112.25:8080", "219.93.101.63:80", "45.166.93.113:999", "43.225.151.82:1120", "180.248.240.22:8080", "95.173.218.67:8082", "95.173.218.74:8081", "41.191.203.167:80", "109.122.197.81:10808", "186.96.111.214:999", "159.65.11.208:8080", "147.75.34.105:443", "164.163.43.102:10000", "103.65.237.92:5678", "197.221.234.253:80", "219.93.101.62:80", "130.193.57.247:1080", "160.251.142.232:80", "95.173.218.68:8081", "144.124.227.90:10808", "91.222.238.112:80", "20.27.14.220:8561", "35.152.164.181:3128", "154.65.39.7:80", "59.153.18.74:1120", "138.68.60.8:80", "95.173.218.72:8081", "90.156.169.163:80", "95.173.218.66:8082", "187.243.251.66:999", "211.230.49.122:3128", "20.27.11.248:8561", "195.114.209.50:80", "103.157.200.126:3128", "167.249.52.91:999", "139.59.1.14:80", "93.118.140.224:8090", "47.56.110.204:8989", "143.42.66.91:80", "123.30.154.171:7777", "34.122.187.196:80", "84.39.112.144:3128", "115.127.178.166:6969", "41.191.203.162:80", "213.73.25.230:8080", "170.0.11.11:8080", "200.174.198.32:8888", "58.187.104.67:2120", "160.22.90.91:8818", "210.223.44.230:3128", "43.224.116.218:1120", "52.188.28.218:3128", "103.230.63.86:1120", "176.126.103.194:44214", "4.149.153.123:3128", "200.85.167.254:8080", "35.197.89.213:80", "192.73.244.36:80", "154.61.76.24:8081", "47.74.157.194:80", "213.142.156.97:80", "115.114.77.133:9090", "41.191.203.161:80", "133.18.234.13:80", "46.47.197.210:3128", "23.247.136.254:80", "45.115.113.182:4334", "41.74.91.244:80", "154.65.39.8:80", "81.169.213.169:8888", "188.40.57.101:80", "185.132.1.221:4145", "36.64.62.111:5678", "50.238.47.86:32100", "195.78.100.162:3629", "190.108.84.168:4145", "86.100.63.246:4145", "117.198.221.34:4153", "103.37.82.134:39873", "161.49.100.131:1080", "193.200.151.69:32777", "103.175.37.34:1080", "43.252.237.98:4145", "113.161.254.4:1080", "46.150.102.26:1080", "117.216.46.148:1080", "212.126.5.248:42344", "118.174.14.65:44336", "46.160.90.81:5678", "103.191.218.37:8199", "200.215.160.210:5678", "213.7.196.26:4153", "109.224.12.170:52015", "12.218.209.130:13326", "83.219.1.130:5678", "69.36.63.128:1080", "103.210.31.49:31433", "103.175.80.54:21080", "197.232.43.224:1080", "102.39.233.4:1080", "160.25.8.141:11011", "202.29.218.138:4153", "80.92.227.185:5678", "91.223.52.141:5678", "213.250.198.146:7777", "188.255.199.137:1080", "89.108.73.200:1080", "218.75.224.4:3309", "212.127.95.235:8081", "142.54.229.249:4145", "213.6.68.210:4145", "72.195.34.35:27360", "64.227.131.240:1080", "200.108.190.110:9800", "125.26.4.197:4145", "72.195.34.59:4145", "192.111.134.10:4145", "195.133.196.244:1080", "103.54.217.82:8199", "202.162.212.164:4153", "213.147.107.178:4153", "92.241.92.218:14888", "176.236.37.132:1080", "191.102.82.83:4153", "103.187.38.38:1080", "68.71.249.158:4145", "206.220.175.2:4145", "199.102.107.145:4145", "103.233.103.237:4153", "190.104.249.187:4145", "94.247.241.70:51006", "69.61.200.104:36181", "184.170.249.65:4145", "47.239.133.193:1100", "115.127.107.106:1080", "24.249.199.4:4145", "184.170.248.5:4145", "38.54.71.67:80", "41.223.234.116:37259", "72.211.46.124:4145", "184.178.172.5:15303", "72.223.188.92:4145", "68.71.251.134:4145", "198.8.94.170:4145", "115.127.178.46:6969", "198.199.86.11:80", "139.135.77.34:8082", "103.175.156.242:8070", "105.174.43.194:8080", "183.110.216.159:8090", "200.188.112.141:999", "81.196.74.147:8080", "103.133.26.11:8080", "115.127.181.86:6969", "197.255.126.69:80", "171.238.90.238:2070", "171.238.88.111:2070", "159.203.61.169:3128", "102.209.18.68:8080", "115.127.178.10:6969", "82.103.94.190:8080", "103.69.60.10:8080", "115.127.178.62:6969", "115.127.178.186:6969", "38.183.212.8:999", "203.95.196.153:8080", "177.234.217.84:999", "81.200.150.68:8080", "34.100.129.128:8123", "45.249.77.145:83", "182.53.202.208:8080", "148.230.23.2:999", "103.245.205.173:1120", "134.209.29.120:80", "198.145.118.250:8080", "80.66.89.15:3128", "97.74.87.226:80", "154.79.248.156:5678", "114.108.177.104:60984", "81.12.169.254:4153", "187.157.30.202:4153", "103.121.195.12:61221", "207.154.230.54:14273", "103.239.201.49:58765", "36.37.244.41:5678", "91.200.115.49:1080", "82.180.132.69:80", "103.79.96.202:4153", "181.115.74.172:5678", "27.72.122.228:51067", "190.54.100.74:5678", "37.192.133.82:1080", "202.178.114.61:4145", "183.80.40.51:1117", "115.127.179.190:6969", "103.189.218.76:6969", "200.30.165.2:60606", "187.190.114.60:999", "118.70.151.55:1080", "170.244.0.179:4145", "103.21.68.49:83", "58.147.186.226:8097", "200.110.173.17:3629", "14.241.182.44:5678", "104.236.114.255:25466", "198.23.134.57:8080", "192.214.193.136:8080", "45.80.220.89:1080", "118.91.175.146:5678", "2.63.188.78:1080", "186.250.53.192:8080", "115.127.178.82:6969", "187.86.59.122:80", "59.153.18.174:1120", "34.140.137.151:80", "115.127.179.106:6969", "103.245.204.138:1120", "117.54.114.33:80", "20.242.243.105:3128", "5.45.126.128:8080", "194.87.77.22:80"]
            proxy_mounts = {
                "http://": httpx.HTTPTransport(proxy=f"http://{proxies[int(time.time()) % len(proxies)]}"),
                "https://": httpx.HTTPTransport(proxy=f"https://{proxies[int(time.time()) % len(proxies)]}"),
            }            
            with httpx.Client(proxies=proxy_mounts, timeout=10) as client:
                response = client.get(url)
            print(f"Requesting URL: {url} - Status Code: {response.status_code}")
        except TooManyRedirects:
            raise HTTPException(status_code=404, detail=f"Not found for url: {url}")
        except ConnectionError:
            raise HTTPException(status_code=500, detail=f"Connection error for url: {url}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error for url: {url}. {e}")
        
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
        print(f"Successfully fetched URL: {url}, Status Code: {response.status_code}")
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
        return self.convert_bsoup_to_page(bsoup=bsoup)

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
