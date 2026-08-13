from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page


NO_SCHEDULED_RUN = "NO CORRESPONDE UNA EJECUCIÓN PROGRAMADA"


def now_guayaquil() -> datetime:
    return datetime.now(ZoneInfo("America/Guayaquil"))


def production_target_day(moment: datetime | None = None) -> date | None:
    moment = moment or now_guayaquil()
    weekday = moment.weekday()  # lunes=0
    return {3: moment.date() + timedelta(days=1), 4: moment.date() + timedelta(days=1), 5: moment.date() + timedelta(days=1)}.get(weekday)


def event_key(league: str, match_date: str, home: str, away: str, internal_id: str | None) -> str:
    raw = "|".join([league, match_date, home, away, internal_id or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _card_teams(card: Locator) -> tuple[str, str] | None:
    candidates = []
    for selector in (
        '[class*="CompetitorName"]',
        '[class*="ParticipantName"]',
        '[data-testid*="competitor"]',
    ):
        candidates = [value.strip() for value in card.locator(selector).all_inner_texts() if value.strip()]
        if len(candidates) >= 2:
            return candidates[0], candidates[1]
    lines = [line.strip() for line in card.inner_text().splitlines() if line.strip()]
    ignored = re.compile(r"^(1x2|empate|más de|menos de|hoy|mañana|\d+[.,]\d+)$", re.I)
    candidates = [line for line in lines if not ignored.search(line) and not re.fullmatch(r"\d{1,2}:\d{2}", line)]
    return (candidates[0], candidates[1]) if len(candidates) >= 2 else None


def _league_for(card: Locator) -> str:
    for attr in ("data-league", "data-competition", "aria-label"):
        value = card.get_attribute(attr)
        if value:
            return value.strip()
    ancestor = card.locator("xpath=ancestor::*[.//*[contains(@class,'League') or contains(@class,'Competition')]][1]")
    if ancestor.count():
        labels = ancestor.locator('[class*="League"], [class*="Competition"]').all_inner_texts()
        if labels:
            return labels[0].strip()
    return "NO VERIFICABLE - La tarjeta pública no mostró la liga."


def _authorized(league: str, config: dict[str, Any]) -> str | None:
    normalized = " ".join(league.casefold().split())
    if any(word in normalized for word in ("virtual", "esport", "e-sport", "juvenil", "sub-")):
        return None
    for entry in config["authorized_leagues"]:
        canonical = entry["canonical"]
        country = entry["country"].casefold()
        league_hit = any(term.casefold() in normalized for term in entry["search_terms"])
        country_ok = country in normalized or canonical.casefold() == normalized
        if league_hit and country_ok:
            return canonical
    return None


def _card_date_time(card: Locator, target: date) -> tuple[date, time] | None:
    text = card.inner_text()
    match = re.search(r"\b(\d{1,2})/(\d{1,2})\s*[•·-]\s*([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if match:
        day, month, hour, minute = (int(value) for value in match.groups())
        try:
            return date(target.year, month, day), time(hour, minute)
        except ValueError:
            return None
    time_match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
    if time_match and re.search(r"\bhoy\b", text, re.I):
        return target, time.fromisoformat(time_match.group(0))
    return None


def _discover_authorized_competitions(
    page: Page, config: dict[str, Any], target: date
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for entry in config["authorized_leagues"]:
        page.goto(config["sport_route"], wait_until="domcontentloaded")
        page.get_by_role("button", name="Competiciones", exact=True).wait_for(state="visible")
        page.get_by_role("button", name="Competiciones", exact=True).click()
        country = page.get_by_text(entry["country"], exact=True)
        if not country.count():
            continue
        country.last.click()
        league_link = page.get_by_text(entry["canonical"], exact=True)
        if not league_link.count():
            continue
        league_link.last.click()
        page.wait_for_url(re.compile(r"/deportes/liga/\d+"), timeout=config["navigation_timeout_ms"])
        page.wait_for_timeout(1000)
        league_url = page.url
        cards = page.locator('div[class*="EventBoxWrapper"]')
        for index in range(cards.count()):
            card = cards.nth(index)
            if re.search(r"\bEN VIVO\b", card.inner_text(), re.I):
                continue
            observed = _card_date_time(card, target)
            if not observed or observed[0] != target:
                continue
            teams = _card_teams(card)
            if not teams:
                continue
            home, away = teams
            internal_id = card.get_attribute("data-event-id") or card.get_attribute("data-id")
            key = (entry["canonical"], target.isoformat(), home, away, internal_id or "")
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "record_id": event_key(*key),
                    "league": entry["canonical"],
                    "date": target.isoformat(),
                    "time": observed[1].strftime("%H:%M"),
                    "home": home,
                    "away": away,
                    "url": league_url,
                    "internal_id": internal_id,
                    "status": "PENDIENTE",
                }
            )
    result.sort(key=lambda row: (row["league"], row["time"], row["home"], row["away"]))
    return result


def discover_board(page: Page, config: dict[str, Any], target: date, production: bool = True, limit: int | None = None, after: str | None = None) -> list[dict[str, Any]]:
    if page.url.rstrip("/") != config["sport_route"].rstrip("/"):
        page.goto(config["sport_route"], wait_until="domcontentloaded")
    if production:
        return _discover_authorized_competitions(page, config, target)
    now_tab = page.get_by_role("button", name="Ahora&Próximos", exact=True)
    if now_tab.count():
        now_tab.click()
    page.locator('div[class*="EventBoxWrapper"]').first.wait_for(
        state="attached", timeout=config["navigation_timeout_ms"]
    )
    page.wait_for_timeout(500)
    cards = page.locator('div[class*="EventBoxWrapper"]')
    cutoff = time.fromisoformat(after) if after else None
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for index in range(cards.count()):
        card = cards.nth(index)
        teams = _card_teams(card)
        if not teams:
            continue
        text = card.inner_text()
        time_match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text)
        if not time_match:
            continue
        kickoff = time.fromisoformat(time_match.group(0))
        if cutoff and kickoff < cutoff:
            continue
        league_raw = _league_for(card)
        league = _authorized(league_raw, config) if production else league_raw
        if production and not league:
            continue
        internal_id = card.get_attribute("data-event-id") or card.get_attribute("data-id")
        home, away = teams
        key = (league or league_raw, target.isoformat(), home, away, internal_id or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "record_id": event_key(*key),
                "league": league or league_raw,
                "date": target.isoformat(),
                "time": kickoff.strftime("%H:%M"),
                "home": home,
                "away": away,
                "url": page.url,
                "internal_id": internal_id,
                "status": "PENDIENTE",
            }
        )
    result.sort(key=lambda row: (row["league"], row["time"], row["home"], row["away"]))
    return result[:limit] if limit else result
