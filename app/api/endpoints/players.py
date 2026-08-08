from typing import Optional

from fastapi import APIRouter, Response

from app.schemas import players as schemas
from app.services.players.achievements import TransfermarktPlayerAchievements
from app.services.players.injuries import TransfermarktPlayerInjuries
from app.services.players.jersey_numbers import TransfermarktPlayerJerseyNumbers
from app.services.players.market_value import TransfermarktPlayerMarketValue
from app.services.players.profile import TransfermarktPlayerProfile
from app.services.players.search import TransfermarktPlayerSearch
from app.services.players.stats import TransfermarktPlayerStats
from app.services.players.transfers import TransfermarktPlayerTransfers
from app.utils.cache import cached

router = APIRouter()


@router.get("/search/{player_name}", response_model=schemas.PlayerSearch, response_model_exclude_none=True)
@cached(namespace="players.search", ttl="short")
def search_players(response: Response, player_name: str, page_number: Optional[int] = 1):
    tfmkt = TransfermarktPlayerSearch(query=player_name, page_number=page_number)
    found_players = tfmkt.search_players()
    return found_players


@router.get("/{player_id}/profile", response_model=schemas.PlayerProfile, response_model_exclude_none=True)
@cached(namespace="players.profile", ttl="short")
def get_player_profile(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerProfile(player_id=player_id)
    player_info = tfmkt.get_player_profile()
    return player_info


@router.get("/{player_id}/market_value", response_model=schemas.PlayerMarketValue, response_model_exclude_none=True)
@cached(namespace="players.market_value", ttl="medium")
def get_player_market_value(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerMarketValue(player_id=player_id)
    player_market_value = tfmkt.get_player_market_value()
    return player_market_value


@router.get("/{player_id}/transfers", response_model=schemas.PlayerTransfers, response_model_exclude_none=True)
@cached(namespace="players.transfers", ttl="medium")
def get_player_transfers(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerTransfers(player_id=player_id)
    player_market_value = tfmkt.get_player_transfers()
    return player_market_value


@router.get("/{player_id}/jersey_numbers", response_model=schemas.PlayerJerseyNumbers, response_model_exclude_none=True)
@cached(namespace="players.jersey_numbers", ttl="long")
def get_player_jersey_numbers(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerJerseyNumbers(player_id=player_id)
    player_jerseynumbers = tfmkt.get_player_jersey_numbers()
    return player_jerseynumbers


@router.get("/{player_id}/stats", response_model=schemas.PlayerStats, response_model_exclude_none=True)
@cached(namespace="players.stats", ttl="short")
def get_player_stats(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerStats(player_id=player_id)
    player_stats = tfmkt.get_player_stats()
    return player_stats


@router.get("/{player_id}/injuries", response_model=schemas.PlayerInjuries, response_model_exclude_none=True)
@cached(namespace="players.injuries", ttl="medium")
def get_player_injuries(response: Response, player_id: str, page_number: Optional[int] = 1):
    tfmkt = TransfermarktPlayerInjuries(player_id=player_id, page_number=page_number)
    players_injuries = tfmkt.get_player_injuries()
    return players_injuries


@router.get("/{player_id}/achievements", response_model=schemas.PlayerAchievements, response_model_exclude_none=True)
@cached(namespace="players.achievements", ttl="long")
def get_player_achievements(response: Response, player_id: str):
    tfmkt = TransfermarktPlayerAchievements(player_id=player_id)
    player_achievements = tfmkt.get_player_achievements()
    return player_achievements
