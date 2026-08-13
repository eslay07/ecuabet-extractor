from src.markets import MARKETS, error_market, unavailable_market
from src.validator import validate_json


def test_explicit_twelve_market_states() -> None:
    match = {
        "record_id": "abc",
        "home": "Local",
        "away": "Visitante",
        "markets": [unavailable_market(spec, "2026-08-04T13:00:00-05:00") for spec in MARKETS],
    }
    data = {
        "manifest": [{"record_id": "abc"}],
        "matches": [match],
        "discovered_count": 1,
        "processed_count": 1,
    }
    assert validate_json(data) == []


def test_incomplete_slider_is_rejected() -> None:
    markets = [unavailable_market(spec, "2026-08-04T13:00:00-05:00") for spec in MARKETS]
    markets[1] = {
        "id": 2,
        "name": "Total de goles",
        "status": "VERIFICADO",
        "data": [{"line": "0.5", "selection": "Más de 0.5", "odd": "1.10"}],
        "slider": {"min": 0, "max": 2, "step": 1, "visited_positions": [0, 2], "complete": False},
    }
    data = {
        "manifest": [{"record_id": "abc"}],
        "matches": [{"record_id": "abc", "home": "A", "away": "B", "markets": markets}],
        "discovered_count": 1,
        "processed_count": 1,
    }
    assert any("Deslizador incompleto" in error for error in validate_json(data))


def test_manual_run_without_verified_odds_is_rejected() -> None:
    queried_at = "2026-08-09T22:00:00-05:00"
    markets = [error_market(spec, queried_at, "No encontrado") for spec in MARKETS]
    data = {
        "execution_mode": "MANUAL",
        "manifest": [{"record_id": "abc"}],
        "matches": [
            {
                "record_id": "abc",
                "home": "Deportivo Cuenca",
                "away": "Manta",
                "markets": markets,
            }
        ],
        "discovered_count": 1,
        "processed_count": 1,
    }
    assert any(
        "ningún mercado contiene cuotas verificadas" in error
        for error in validate_json(data)
    )
