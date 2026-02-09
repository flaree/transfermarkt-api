from dataclasses import dataclass

from app.services.base import TransfermarktBase
from app.utils.regex import REGEX_BG_COLOR, REGEX_COUNTRY_ID, REGEX_MEMBERS_DATE
from app.utils.utils import extract_from_url, remove_str, safe_regex, safe_split
from app.utils.xpath import Clubs


@dataclass
class TransfermarktClubProfile(TransfermarktBase):
    """
    A class for retrieving and parsing the profile information of a football club from Transfermarkt.

    Args:
        club_id (str): The unique identifier of the football club.
        URL (str): The URL template for the club's profile page on Transfermarkt.
    """

    club_id: str = None
    URL: str = "https://www.transfermarkt.com/-/mitarbeiter/verein/{club_id}"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktClubProfile class."""
        self.URL = self.URL.format(club_id=self.club_id)
        self.page = self.request_url_page()
        # self.raise_exception_if_not_found(xpath=Clubs.Profile.URL)

    def get_club_profile(self) -> dict:
        """
        Retrieve and parse the profile information of the football club from Transfermarkt.

        This method extracts various attributes of the club's profile, such as name, official name, address, contact
        information, stadium details, and more.

        Returns:
            dict: A dictionary containing the club's profile information.
        """
        self.response["id"] = self.club_id
        self.response["url"] = self.get_text_by_xpath(Clubs.Profile.URL) or ""
        self.response["name"] = self.get_text_by_xpath(Clubs.Profile.NAME)
        self.response["manager"] = self.get_text_by_xpath(Clubs.Profile.MANAGER)
        self.response["officialName"] = None
        self.response["image"] = ""
        self.response["legalForm"] = None
        self.response["addressLine1"] = None
        self.response["addressLine2"] = None
        self.response["addressLine3"] = None
        self.response["tel"] = None
        self.response["fax"] = None
        self.response["website"] = None
        self.response["foundedOn"] = None
        self.response["members"] = None
        self.response["membersDate"] = None
        self.response["otherSports"] = None
        self.response["colors"] = []
        self.response["stadiumName"] = self.get_text_by_xpath(Clubs.Profile.STADIUM_NAME) or ""
        self.response["stadiumSeats"] = 1
        self.response["currentTransferRecord"] = "1"
        self.response["currentMarketValue"] = None
        self.response["confederation"] = None
        self.response["fifaWorldRanking"] = None
        self.response["squad"] = {
            "size": 0,
            "averageAge": 0.0,
            "foreigners": 0,
            "nationalTeamPlayers": 0,
        }
        self.response["league"] = {
            "id": None,
            "name": None,
            "countryId": None,
            "countryName": None,
            "tier": None,
        }
        self.response["historicalCrests"] = []

        return self.response
