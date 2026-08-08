class BotChallengeError(Exception):
    """
    Raised when Transfermarkt serves an anti-bot challenge instead of the requested page.

    This is deliberately not an HTTPException: a challenge is a transient upstream block, not a
    property of the resource being requested. Callers catch it to fall back to stale cached data
    before it ever reaches the client.

    Args:
        url (str): The URL that was challenged.
        status_code (int): The HTTP status code returned with the challenge.
    """

    def __init__(self, url: str, status_code: int) -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(f"Bot challenge ({status_code}) for url: {url}")
