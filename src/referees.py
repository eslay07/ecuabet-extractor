from __future__ import annotations

from typing import Any


NOT_VERIFIABLE_REFEREE = (
    "NO VERIFICABLE - No se encontró una designación arbitral oficial publicada "
    "al momento de la consulta."
)


def unavailable_referee(queried_at: str) -> dict[str, Any]:
    return {
        "name": NOT_VERIFIABLE_REFEREE,
        "source_url": None,
        "queried_at": queried_at,
        "status": "NO VERIFICABLE",
    }


def validate_referee(record: dict[str, Any]) -> None:
    if record.get("status") == "VERIFICADO":
        if not record.get("name") or not record.get("source_url"):
            raise ValueError("Un árbitro VERIFICADO requiere nombre y URL oficial")
    elif record.get("name") != NOT_VERIFIABLE_REFEREE:
        raise ValueError("El estado arbitral no verificable no usa el texto obligatorio")

