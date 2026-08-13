from __future__ import annotations

from collections.abc import Iterable
from typing import Any

VERIFIED = "VERIFICADO"
UNAVAILABLE = "NO DISPONIBLE EN ECUABET"
EXTRACTION_ERROR = "ERROR DE EXTRACCIÓN"
UNAVAILABLE_MESSAGE = (
    "NO DISPONIBLE EN ECUABET - Mercado no publicado para este partido "
    "al momento de la consulta."
)
NOT_VERIFIABLE_ECUABET = "NO VERIFICABLE EN ECUABET."

MARKETS: list[dict[str, Any]] = [
    {"id": 1, "name": "1x2", "tab": "Principal", "aliases": ["1x2"]},
    {"id": 2, "name": "Total de goles", "tab": "Principal", "aliases": ["Total"]},
    {
        "id": 3,
        "name": "Ambos equipos marcan",
        "tab": "Principal",
        "aliases": ["Ambos equipos marcan"],
    },
    {
        "id": 4,
        "name": "Total Tiros de Esquina",
        "tab": "Tiros esquina",
        "aliases": ["Total Tiros De Esquina", "Total Tiros de Esquina"],
    },
    {
        "id": 5,
        "name": "Hándicap en Tiros de Esquina",
        "tab": "Tiros esquina",
        "aliases": ["Hándicap en Tiros de Esquina", "Hándicap Tiros de Esquina"],
    },
    {
        "id": 6,
        "name": "Equipo local Total de Tiros de Esquina",
        "tab": "Tiros esquina",
        "aliases": ["{home} Total de Tiros de Esquina", "{home} - Total de Tiros de Esquina"],
    },
    {
        "id": 7,
        "name": "Equipo visitante Total de Tiros de Esquina",
        "tab": "Tiros esquina",
        "aliases": ["{away} Total de Tiros de Esquina", "{away} - Total de Tiros de Esquina"],
    },
    {
        "id": 8,
        "name": "1ª mitad - Total Tiros de Esquina",
        "tab": "Tiros esquina",
        "aliases": ["1ª mitad - Total Tiros de Esquina"],
    },
    {
        "id": 9,
        "name": "1ª mitad - Total de Tiros de Esquina del equipo local",
        "tab": "Tiros esquina",
        "aliases": [
            "1ª mitad - Total de Tiros de Esquina de {home}",
            "1ª mitad - {home} Total de Tiros de Esquina",
        ],
    },
    {
        "id": 10,
        "name": "1ª mitad - Total de Tiros de Esquina del equipo visitante",
        "tab": "Tiros esquina",
        "aliases": [
            "1ª mitad - Total de Tiros de Esquina de {away}",
            "1ª mitad - {away} Total de Tiros de Esquina",
        ],
    },
    {
        "id": 11,
        "name": "Tarjetas 1x2",
        "tab": "Tarjetas",
        "aliases": ["Tarjetas 1x2"],
    },
    {
        "id": 12,
        "name": "Total de tarjetas",
        "tab": "Tarjetas",
        "aliases": ["Total de tarjetas"],
    },
]


def aliases_for(market: dict[str, Any], home: str, away: str) -> list[str]:
    return [alias.format(home=home, away=away) for alias in market["aliases"]]


def unavailable_market(market: dict[str, Any], queried_at: str) -> dict[str, Any]:
    return {
        "id": market["id"],
        "name": market["name"],
        "status": UNAVAILABLE,
        "message": UNAVAILABLE_MESSAGE,
        "queried_at": queried_at,
        "data": [],
    }


def error_market(market: dict[str, Any], queried_at: str, error: str) -> dict[str, Any]:
    return {
        "id": market["id"],
        "name": market["name"],
        "status": EXTRACTION_ERROR,
        "error": error,
        "queried_at": queried_at,
        "data": [],
    }


def dedupe_selections(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("market", "")),
            str(row.get("line", "")),
            str(row.get("selection", "")),
            str(row.get("odd", "")),
        )
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result

