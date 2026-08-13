from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page

from .browser import PublicAccessError
from .markets import MARKETS, VERIFIED, aliases_for, dedupe_selections, error_market, unavailable_market
from .manual import normalized_team_tokens, team_tokens_match
from .referees import unavailable_referee


CheckpointCallback = Callable[[dict[str, Any]], None]


class DetailedMarketsUnavailable(RuntimeError):
    """The public event card is visible but its expanded panel did not open."""


def timestamp() -> str:
    return datetime.now(ZoneInfo("America/Guayaquil")).isoformat(timespec="seconds")


def _dismiss_optional_login(page: Page) -> bool:
    """Close Ecuabet's recurring login overlay without touching login controls.

    The public sports page can display this modal after the page has already
    loaded.  Its backdrop sits above the event list, so every navigation step
    must be able to clear it again.
    """
    closed = False
    for _ in range(3):
        modal = page.locator('div.modal input[name="email"]:visible')
        if not modal.count():
            return closed
        close = page.locator(
            'div.modal label[for="m-modal-login"].absolute:visible'
        )
        if not close.count():
            raise PublicAccessError(
                "El banner de inicio de sesión bloquea la cartelera y no expone "
                "un control público de cierre."
            )
        close.first.click(timeout=3000)
        page.wait_for_timeout(250)
        closed = True
    if page.locator('div.modal input[name="email"]:visible').count():
        raise PublicAccessError(
            "El banner de inicio de sesión reapareció después de tres cierres controlados."
        )
    return closed


def _mandatory_login_visible(page: Page) -> bool:
    return bool(page.locator('div.modal input[name="email"]:visible').count())


def _click_with_banner_guard(
    locator: Locator, *, timeout: int = 10000, delay: int | None = None
) -> None:
    """Click a safe navigation control and recover once from the observed modal."""
    page = locator.page
    _dismiss_optional_login(page)
    kwargs: dict[str, Any] = {"timeout": timeout}
    if delay is not None:
        kwargs["delay"] = delay
    try:
        locator.click(**kwargs)
    except Exception:
        if not _mandatory_login_visible(page):
            raise
        _dismiss_optional_login(page)
        locator.click(**kwargs)
    _dismiss_optional_login(page)


def _click_first_visible(locator: Locator) -> bool:
    for index in range(locator.count()):
        candidate = locator.nth(index)
        if candidate.is_visible():
            _click_with_banner_guard(candidate, timeout=10000)
            return True
    return False


def _prepare_football_home(page: Page) -> None:
    """Open Deportes > Fútbol and expand the public event list."""
    deadline = time.monotonic() + 30
    football: Locator | None = None
    while time.monotonic() < deadline:
        _dismiss_optional_login(page)
        menu_item = page.locator(
            'span[class*="ClickableSportMenuSportName"]',
            has_text=re.compile(r"^Fútbol$"),
        )
        top_button = page.locator(
            'button[class*="TopSportBarButton"]', has_text=re.compile(r"^Fútbol$")
        )
        for candidate in (menu_item, top_button):
            for index in range(candidate.count()):
                if candidate.nth(index).is_visible():
                    football = candidate.nth(index)
                    break
            if football is not None:
                break
        if football is not None:
            break
        page.wait_for_timeout(500)
    if football is None:
        raise TimeoutError(
            "La página Deportes no mostró el selector público Fútbol dentro de 30 segundos."
        )
    _dismiss_optional_login(page)
    _click_with_banner_guard(football, timeout=10000)
    page.wait_for_timeout(700)
    _dismiss_optional_login(page)

    show_all = page.get_by_role("button", name="Ver todos los eventos", exact=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        _dismiss_optional_login(page)
        if _click_first_visible(show_all):
            page.wait_for_timeout(700)
            _dismiss_optional_login(page)
            break
        page.wait_for_timeout(400)
    else:
        raise TimeoutError(
            "La sección Fútbol no mostró el botón público Ver todos los eventos."
        )
    page.locator('div[class*="EventBoxWrapper"]').first.wait_for(
        state="attached", timeout=30000
    )


def _matching_card(cards: Locator, match: dict[str, Any]) -> Locator | None:
    home_tokens = normalized_team_tokens(match["home"])
    away_tokens = normalized_team_tokens(match["away"])
    target_label = ""
    try:
        target = date.fromisoformat(match["date"])
        target_label = target.strftime("%d/%m")
    except (KeyError, ValueError):
        pass
    for index in range(cards.count()):
        card = cards.nth(index)
        text = card.inner_text()
        card_tokens = normalized_team_tokens(text)
        date_labels = re.findall(r"\b\d{1,2}/\d{1,2}\b", text)
        date_matches = not target_label or not date_labels or target_label in date_labels
        if (
            team_tokens_match(home_tokens, card_tokens)
            and team_tokens_match(away_tokens, card_tokens)
            and date_matches
        ):
            return card
    return None


def _match_exists_in_sports_search(page: Page, match: dict[str, Any]) -> bool:
    _dismiss_optional_login(page)
    search = page.get_by_placeholder(
        "Ingrese el nombre del equipo o del campeonato", exact=True
    )
    if not search.count() or not search.first.is_visible():
        return False
    results = page.locator(
        'div[class*="EventSearchResultList"] div[class*="EventBoxWrapper"]'
    )
    try:
        for team in (match["home"], match["away"]):
            _dismiss_optional_login(page)
            query = team.title() if team.islower() else team
            search.first.fill(query)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if _matching_card(results, match) is not None:
                    return True
                page.wait_for_timeout(400)
            search.first.press("Control+A")
            search.first.press("Backspace")
            page.wait_for_timeout(250)
        return False
    finally:
        search.first.press("Control+A")
        search.first.press("Backspace")
        page.wait_for_timeout(250)


def _find_card(page: Page, match: dict[str, Any]) -> Locator:
    cards = page.locator('div[class*="EventBoxWrapper"]')
    previous_count = -1
    unchanged = 0
    for _ in range(8):
        _dismiss_optional_login(page)
        count = cards.count()
        found = _matching_card(cards, match)
        if found is not None:
            return found
        unchanged = unchanged + 1 if count == previous_count else 0
        if not count or unchanged >= 2:
            break
        previous_count = count
        cards.last.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    raise LookupError(f"Partido no encontrado en la cartelera: {match['home']} vs {match['away']}")


def _open_details(page: Page, match: dict[str, Any]) -> Locator:
    card: Locator | None = None
    if page.url.rstrip("/") != match["url"].rstrip("/"):
        page.goto(match["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        _dismiss_optional_login(page)
    if page.url.rstrip("/") == "https://ecuabet.com/deportes":
        _dismiss_optional_login(page)
        try:
            # Ecuabet can already publish tomorrow's event card in Destacados.
            # Preserve that exact dated card instead of navigating away from it.
            card = _find_card(page, match)
        except LookupError:
            _prepare_football_home(page)
    if page.url.rstrip("/") == "https://ecuabet.com/deportes/66":
        page.locator('button[class*="SportOverviewTab"]').first.wait_for(state="attached")
        now_tab = page.get_by_role("button", name="Ahora&Próximos", exact=True)
        if now_tab.count():
            now_tab.click()
            page.locator('div[class*="EventBoxWrapper"]').first.wait_for(state="attached")
            page.wait_for_timeout(500)
    _dismiss_optional_login(page)
    if card is None:
        try:
            card = _find_card(page, match)
        except LookupError as error:
            if _match_exists_in_sports_search(page, match):
                raise LookupError(
                    "El partido sí está publicado en la búsqueda de Deportes para la fecha "
                    "indicada, pero Ecuabet no expuso su tarjeta pública de detalles."
                ) from error
            raise
    root = card.locator('div[class*="EventDetailsMarketBoxRoot"]')
    if not root.count():
        button = card.locator('button[class*="EventDetailsButton"]')
        if not button.count():
            raise LookupError("La tarjeta no expone el botón público de detalles")
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        button.first.hover()
        page.wait_for_timeout(250)
        _click_with_banner_guard(button.first, delay=120)
        page.wait_for_timeout(400)
        details = card.locator(
            'button[class*="EventDetailsTab"], div[class*="EventDetailsMarketBoxRoot"]'
        )
        if not details.count():
            # Retry only once after clearing any overlay that appeared during
            # the first click.
            _click_with_banner_guard(button.first, delay=120)
            page.wait_for_timeout(400)
        try:
            details.first.wait_for(state="attached", timeout=6000)
            page.wait_for_timeout(500)
        except Exception:
            # The collapsed card still contains public 1x2 and Total odds.
            # Keep it available so those real values are not discarded.
            pass
    return card


def _extract_collapsed_market(
    card: Locator, match: dict[str, Any], market: dict[str, Any], queried_at: str
) -> dict[str, Any] | None:
    """Read the two real markets Ecuabet exposes on the collapsed public card."""
    if market["id"] not in {1, 2}:
        return None
    boxes = card.locator(
        'div[class*="MarketBoxWrapper"] > div[class*="MarketBoxContainer"]'
    )
    index = market["id"] - 1
    if boxes.count() <= index:
        return None
    rows = _read_visible_selections(boxes.nth(index), market["name"])
    if not rows:
        return None

    labels = " ".join(row["selection"] for row in rows)
    normalized_labels = normalized_team_tokens(labels)
    if market["id"] == 1:
        if (
            "empate" not in labels.casefold()
            or not team_tokens_match(normalized_team_tokens(match["home"]), normalized_labels)
            or not team_tokens_match(normalized_team_tokens(match["away"]), normalized_labels)
        ):
            return None
    else:
        lowered = labels.casefold()
        if "más de" not in lowered or "menos de" not in lowered:
            return None
        for row in rows:
            line = re.search(r"[-+]?\d+(?:[.,]\d+)?", row["selection"])
            row["line"] = line.group(0) if line else ""

    return {
        "id": market["id"],
        "name": market["name"],
        "status": VERIFIED,
        "queried_at": queried_at,
        "coverage": (
            "CUOTAS VISIBLES EN LA TARJETA PÚBLICA; "
            "EL PANEL DE MERCADOS AMPLIADOS NO SE ABRIÓ"
        ),
        "data": dedupe_selections(rows),
    }


def _select_tab(card: Locator, name: str) -> bool:
    tabs = card.locator('button[class*="EventDetailsTabContainer"]')
    for index in range(tabs.count()):
        if tabs.nth(index).inner_text().strip().casefold() == name.casefold():
            _click_with_banner_guard(tabs.nth(index))
            card.page.wait_for_timeout(500)
            return True
    return False


def _market_headers(card: Locator) -> Locator:
    return card.locator('div[class^="EventDetailsMarketName-sc-"]:not([class*="Wrapper"])')


def _find_header(card: Locator, aliases: list[str]) -> Locator | None:
    headers = _market_headers(card)
    wanted = {" ".join(alias.casefold().split()) for alias in aliases}
    for index in range(headers.count()):
        actual = " ".join(headers.nth(index).inner_text().casefold().split())
        if actual in wanted:
            return headers.nth(index)
    return None


def _root_for_header(header: Locator) -> Locator:
    root = header.locator("xpath=ancestor::div[contains(@class,'EventDetailsMarketBoxRoot')][1]")
    return root if root.count() else header.locator("xpath=..")


def _close_open_markets(card: Locator) -> None:
    headers = _market_headers(card)
    for index in range(headers.count()):
        header = headers.nth(index)
        root = _root_for_header(header)
        visible_values = root.locator('[class*="OddValue-"]:visible')
        if visible_values.count():
            header.scroll_into_view_if_needed()
            header.hover()
            _click_with_banner_guard(header, delay=80)
            card.page.wait_for_timeout(150)


def _read_visible_selections(root: Locator, market_name: str, line: str = "") -> list[dict[str, str]]:
    labels = root.locator('[class*="OddLabel-"]')
    values = root.locator('[class*="OddValue-"]')
    count = min(labels.count(), values.count())
    rows: list[dict[str, str]] = []
    for index in range(count):
        selection = labels.nth(index).inner_text().strip()
        odd = values.nth(index).inner_text().strip()
        if selection and odd:
            rows.append({"market": market_name, "line": line, "selection": selection, "odd": odd})
    return rows


def _fingerprint(root: Locator) -> str:
    return "|".join(root.locator('[class*="OddLabel-"], [class*="OddValue-"], [class*="SliderThumbLabel"]').all_inner_texts())


def _wait_stable(root: Locator, timeout_ms: int) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    previous = None
    equal = 0
    while time.monotonic() < deadline:
        current = _fingerprint(root)
        equal = equal + 1 if current == previous and current else 0
        if equal >= 2:
            return
        previous = current
        root.page.wait_for_timeout(150)
    raise TimeoutError("El mercado no alcanzó un estado DOM estable")


def _line_from_root(root: Locator, rows: list[dict[str, str]]) -> str:
    label = root.locator('[class*="EventDetailsSliderThumbLabel"]')
    if label.count():
        return label.first.inner_text().strip()
    for row in rows:
        match = re.search(r"[-+]?\d+(?:[.,]\d+)?", row["selection"])
        if match:
            return match.group(0)
    return ""


def _extract_open_market(root: Locator, market: dict[str, Any], timeout_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    slider = root.locator('input[type="range"]')
    if not slider.count():
        _wait_stable(root, timeout_ms)
        rows = _read_visible_selections(root, market["name"])
        for row in rows:
            row["line"] = _line_from_root(root, rows)
        return dedupe_selections(rows), None

    control = slider.first
    minimum = int(float(control.get_attribute("min") or "0"))
    maximum = int(float(control.get_attribute("max") or "0"))
    step = int(float(control.get_attribute("step") or "1"))
    if step <= 0 or maximum < minimum:
        raise ValueError("Rango de deslizador inválido")
    expected = ((maximum - minimum) // step) + 1
    _dismiss_optional_login(root.page)
    control.press("Home")
    all_rows: list[dict[str, Any]] = []
    visited: list[int] = []
    for offset, value in enumerate(range(minimum, maximum + 1, step)):
        _wait_stable(root, timeout_ms)
        current_rows = _read_visible_selections(root, market["name"])
        line = _line_from_root(root, current_rows)
        for row in current_rows:
            row["line"] = line
            row["slider_position"] = value
            all_rows.append(row)
        visited.append(value)
        if offset < expected - 1:
            _dismiss_optional_login(root.page)
            control.press("ArrowRight")
    if len(visited) != expected or visited[0] != minimum or visited[-1] != maximum:
        raise RuntimeError("No se pudo demostrar el recorrido completo del deslizador")
    return dedupe_selections(all_rows), {
        "min": minimum,
        "max": maximum,
        "step": step,
        "expected_positions": expected,
        "visited_positions": visited,
        "complete": True,
    }


def extract_market(card: Locator, match: dict[str, Any], market: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    queried_at = timestamp()
    _dismiss_optional_login(card.page)
    if not card.locator('div[class*="EventDetailsMarketBoxRoot"]').count():
        collapsed = _extract_collapsed_market(card, match, market, queried_at)
        if collapsed is not None:
            return collapsed
        raise DetailedMarketsUnavailable(
            "La tarjeta pública está visible, pero Ecuabet no abrió el panel "
            "de mercados detallados después de cerrar el banner y reintentar una vez."
        )
    if not _select_tab(card, market["tab"]):
        collapsed = _extract_collapsed_market(card, match, market, queried_at)
        if collapsed is not None:
            return collapsed
        return unavailable_market(market, queried_at)
    _close_open_markets(card)
    header = _find_header(card, aliases_for(market, match["home"], match["away"]))
    if header is None:
        collapsed = _extract_collapsed_market(card, match, market, queried_at)
        if collapsed is not None:
            return collapsed
        return unavailable_market(market, queried_at)
    header.scroll_into_view_if_needed()
    header.hover()
    _click_with_banner_guard(header, delay=100)
    root = _root_for_header(header)
    root.locator('[class*="OddValue-"]').first.wait_for(state="visible", timeout=timeout_ms)
    card.page.wait_for_timeout(250)
    try:
        rows, slider = _extract_open_market(root, market, timeout_ms)
        if not rows:
            raise RuntimeError("El mercado se abrió, pero no expuso selecciones y cuotas")
        result: dict[str, Any] = {
            "id": market["id"],
            "name": market["name"],
            "status": VERIFIED,
            "queried_at": queried_at,
            "data": rows,
        }
        if slider:
            result["slider"] = slider
        return result
    finally:
        _dismiss_optional_login(card.page)
        header.scroll_into_view_if_needed()
        _click_with_banner_guard(header, delay=80)
        card.page.wait_for_timeout(150)


def extract_match(page: Page, match: dict[str, Any], timeout_ms: int, checkpoint: CheckpointCallback | None = None) -> dict[str, Any]:
    output = dict(match)
    existing = {int(item["id"]): item for item in output.get("markets", [])}
    reloads = int(output.get("reloads", 0))
    card: Locator | None = _open_details(page, output)
    detailed_terminal_error: str | None = None
    for market in MARKETS:
        if existing.get(market["id"], {}).get("status") == VERIFIED:
            continue
        if detailed_terminal_error is not None and market["id"] >= 3:
            value = error_market(market, timestamp(), detailed_terminal_error)
            existing[market["id"]] = value
            output["markets"] = [
                existing[item["id"]] for item in MARKETS if item["id"] in existing
            ]
            output["reloads"] = reloads
            output["last_updated"] = timestamp()
            if checkpoint:
                checkpoint(output)
            continue
        try:
            if card is None:
                card = _open_details(page, output)
            value = extract_market(card, output, market, timeout_ms)
        except PublicAccessError:
            raise
        except DetailedMarketsUnavailable as first_error:
            if reloads == 0:
                reloads = 1
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                try:
                    card = _open_details(page, output)
                    value = extract_market(card, output, market, timeout_ms)
                except PublicAccessError:
                    raise
                except Exception as second_error:
                    detailed_terminal_error = (
                        f"{type(second_error).__name__}: {second_error}"
                    )
                    value = error_market(
                        market, timestamp(), detailed_terminal_error
                    )
                    card = None
            else:
                detailed_terminal_error = f"{type(first_error).__name__}: {first_error}"
                value = error_market(market, timestamp(), detailed_terminal_error)
        except Exception as first_error:
            if reloads == 0:
                reloads = 1
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                try:
                    card = _open_details(page, output)
                    value = extract_market(card, output, market, timeout_ms)
                except PublicAccessError:
                    raise
                except Exception as second_error:
                    if isinstance(second_error, DetailedMarketsUnavailable):
                        detailed_terminal_error = (
                            f"{type(second_error).__name__}: {second_error}"
                        )
                    value = error_market(market, timestamp(), f"{type(second_error).__name__}: {second_error}")
                    card = None
            else:
                value = error_market(market, timestamp(), f"{type(first_error).__name__}: {first_error}")
                card = None
        existing[market["id"]] = value
        output["markets"] = [existing[item["id"]] for item in MARKETS if item["id"] in existing]
        output["reloads"] = reloads
        output["last_updated"] = timestamp()
        if checkpoint:
            checkpoint(output)
    output["referee"] = output.get("referee") or unavailable_referee(timestamp())
    output["status"] = "PROCESADO"
    output["last_updated"] = timestamp()
    if checkpoint:
        checkpoint(output)
    if card is not None:
        try:
            _dismiss_optional_login(page)
            if card.locator('div[class*="EventDetailsMarketBoxRoot"]').count():
                close = card.locator('button[class*="EventDetailsButton"]').first
                close.scroll_into_view_if_needed()
                _click_with_banner_guard(close, delay=80, timeout=3000)
                page.wait_for_timeout(200)
        except Exception:
            pass
    return output


def normalize_manual_market(raw: dict[str, Any]) -> dict[str, Any]:
    market = dict(raw)
    market.setdefault("queried_at", None)
    normalized: list[dict[str, Any]] = []
    for row in market.get("data", []):
        if "selections" in row:
            for selection in row["selections"]:
                normalized.append(
                    {
                        "market": market["name"],
                        "line": str(row.get("line", "")),
                        "selection": str(selection.get("selection", "")),
                        "odd": str(selection.get("odd", "")),
                        "slider_position": row.get("position"),
                    }
                )
        elif "values" in row:
            for value in row["values"]:
                normalized.append(
                    {"market": market["name"], "line": "", "selection": str(row.get("label", "")), "odd": str(value)}
                )
        else:
            normalized.append(
                {
                    "market": market["name"],
                    "line": str(row.get("line", "")),
                    "selection": str(row.get("selection", "")),
                    "odd": str(row.get("odd", "")),
                }
            )
    market["data"] = dedupe_selections(normalized)
    if "slider" in market and "min" in market["slider"] and "max" in market["slider"]:
        slider = dict(market["slider"])
        minimum = int(slider["min"])
        maximum = int(slider["max"])
        step = int(slider.get("step", 1))
        positions = list(range(minimum, maximum + 1, step))
        slider.update(
            {
                "expected_positions": len(positions),
                "visited_positions": positions,
                "complete": int(slider.get("visited", len(positions))) == len(positions),
            }
        )
        market["slider"] = slider
    elif "slider" in market:
        market["alternatives_display"] = dict(market.pop("slider"))
    return market
