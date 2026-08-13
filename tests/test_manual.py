from datetime import date

import pytest

from src.manual import (
    MAX_MANUAL_MATCHES,
    ManualInputError,
    normalized_team_tokens,
    parse_manual_line,
    parse_manual_matches,
    team_tokens_match,
)


def test_minimal_manual_format() -> None:
    parsed = parse_manual_line("Real Madrid vs Barcelona")
    assert parsed["home"] == "Real Madrid"
    assert parsed["away"] == "Barcelona"
    assert parsed["time"] == "SIN HORA"


def test_manual_manifest_can_use_the_deportes_home_page() -> None:
    manifest = parse_manual_matches(
        ["Deportivo Cuenca vs Manta"],
        date(2026, 8, 10),
        "https://ecuabet.com/deportes",
    )
    assert manifest[0]["url"] == "https://ecuabet.com/deportes"


def test_extended_manual_format() -> None:
    parsed = parse_manual_line("LaLiga | 20:00 | Real Madrid vs Barcelona")
    assert parsed["league"] == "LaLiga"
    assert parsed["time"] == "20:00"


def test_numbered_lines_and_fifty_match_limit() -> None:
    lines = [f"{index + 1}. Local {index} vs Visitante {index}" for index in range(MAX_MANUAL_MATCHES)]
    manifest = parse_manual_matches(lines, date(2026, 8, 9), "https://ecuabet.com/deportes/66")
    assert len(manifest) == 50
    assert all(row["source"] == "SELECCIÓN MANUAL DEL USUARIO" for row in manifest)


def test_more_than_fifty_matches_is_rejected() -> None:
    lines = [f"Local {index} vs Visitante {index}" for index in range(MAX_MANUAL_MATCHES + 1)]
    with pytest.raises(ManualInputError, match="máximo 50"):
        parse_manual_matches(lines, date(2026, 8, 9), "https://ecuabet.com/deportes/66")


def test_duplicate_and_invalid_format_are_rejected() -> None:
    with pytest.raises(ManualInputError, match="duplicado"):
        parse_manual_matches(
            ["Real Madrid vs Barcelona", "real madrid vs barcelona"],
            date(2026, 8, 9),
            "https://ecuabet.com/deportes/66",
        )
    with pytest.raises(ManualInputError, match="Use 'Equipo local vs Equipo visitante'"):
        parse_manual_line("Real Madrid - Barcelona")


def test_team_matching_ignores_accents_and_small_spelling_variations() -> None:
    card = normalized_team_tokens("Inter Milan - Venezia FC")
    assert team_tokens_match(normalized_team_tokens("Inter de Milán"), card)
    assert team_tokens_match(normalized_team_tokens("Venecia"), card)


def test_team_matching_accepts_deportivo_abbreviation() -> None:
    card = normalized_team_tokens("Dep. Cuenca - Manta FC")
    assert team_tokens_match(normalized_team_tokens("Deportivo Cuenca"), card)
    assert team_tokens_match(normalized_team_tokens("Manta"), card)
