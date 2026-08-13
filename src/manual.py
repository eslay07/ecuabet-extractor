from __future__ import annotations

import re
import unicodedata
from datetime import date, time
from difflib import SequenceMatcher
from typing import Any, Iterable

from .discovery import event_key


MAX_MANUAL_MATCHES = 50
DEFAULT_MANUAL_LEAGUE = "SELECCIÓN MANUAL"


class ManualInputError(ValueError):
    pass


def _clean_line(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", value)
    return " ".join(value.split())


def _split_match(value: str) -> tuple[str, str]:
    parts = re.split(r"\s+(?:vs\.?|versus)\s+", value, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise ManualInputError(
            f"Formato inválido: {value!r}. Use 'Equipo local vs Equipo visitante'."
        )
    home, away = (" ".join(part.split()) for part in parts)
    if len(home) < 2 or len(away) < 2:
        raise ManualInputError(f"Los dos equipos son obligatorios: {value!r}")
    if home.casefold() == away.casefold():
        raise ManualInputError(f"Los equipos no pueden ser iguales: {value!r}")
    return home, away


def _parse_time(value: str) -> str:
    try:
        return time.fromisoformat(value.strip()).strftime("%H:%M")
    except ValueError as error:
        raise ManualInputError(f"Hora inválida: {value!r}. Use HH:MM.") from error


def parse_manual_line(value: str) -> dict[str, str]:
    raw = _clean_line(value)
    fields = [field.strip() for field in raw.split("|")]
    if len(fields) > 3:
        raise ManualInputError(f"Demasiados campos separados por '|': {value!r}")

    league = DEFAULT_MANUAL_LEAGUE
    kickoff = "SIN HORA"
    match_text = fields[-1]
    if len(fields) == 2:
        if re.fullmatch(r"\d{1,2}:\d{2}", fields[0]):
            kickoff = _parse_time(fields[0])
        else:
            league = fields[0] or DEFAULT_MANUAL_LEAGUE
    elif len(fields) == 3:
        league = fields[0] or DEFAULT_MANUAL_LEAGUE
        kickoff = _parse_time(fields[1])
    home, away = _split_match(match_text)
    return {
        "league": league,
        "time": kickoff,
        "home": home,
        "away": away,
        "manual_input": raw,
    }


def parse_manual_matches(
    lines: Iterable[str], target_date: date, public_url: str
) -> list[dict[str, Any]]:
    cleaned = [_clean_line(line) for line in lines if _clean_line(line)]
    if not cleaned:
        raise ManualInputError("Escriba al menos un partido.")
    if len(cleaned) > MAX_MANUAL_MATCHES:
        raise ManualInputError(
            f"Se permiten como máximo {MAX_MANUAL_MATCHES} partidos; recibió {len(cleaned)}."
        )

    manifest: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line_number, line in enumerate(cleaned, start=1):
        try:
            parsed = parse_manual_line(line)
        except ManualInputError as error:
            raise ManualInputError(f"Línea {line_number}: {error}") from error
        key = (
            target_date.isoformat(),
            parsed["home"].casefold(),
            parsed["away"].casefold(),
        )
        if key in seen:
            raise ManualInputError(
                f"Línea {line_number}: partido duplicado ({parsed['home']} vs {parsed['away']})."
            )
        seen.add(key)
        record_id = event_key(
            parsed["league"],
            target_date.isoformat(),
            parsed["home"],
            parsed["away"],
            None,
        )
        manifest.append(
            {
                "record_id": record_id,
                "league": parsed["league"],
                "date": target_date.isoformat(),
                "time": parsed["time"],
                "home": parsed["home"],
                "away": parsed["away"],
                "url": public_url,
                "internal_id": None,
                "status": "PENDIENTE",
                "source": "SELECCIÓN MANUAL DEL USUARIO",
                "manual_input": parsed["manual_input"],
            }
        )
    return manifest


def normalized_team_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", normalized)
    ignored = {
        "de",
        "del",
        "la",
        "el",
        "fc",
        "cf",
        "ac",
        "cd",
        "sd",
        "sc",
        "club",
        "futbol",
        "football",
        "deportivo",
        "deportiva",
        "dep",
    }
    return {token for token in tokens if token not in ignored}


def team_tokens_match(expected: set[str], observed: set[str]) -> bool:
    """Match team tokens while tolerating accents and small spelling variations."""
    if not expected:
        return False
    for token in expected:
        if token in observed:
            continue
        close_match = any(
            len(token) >= 5
            and len(candidate) >= 5
            and SequenceMatcher(None, token, candidate).ratio() >= 0.84
            for candidate in observed
        )
        if not close_match:
            return False
    return True
