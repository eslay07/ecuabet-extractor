from __future__ import annotations

from src.extractor import _dismiss_optional_login, _extract_collapsed_market


class TextLocator:
    def __init__(self, values: list[str]):
        self.values = values

    def count(self) -> int:
        return len(self.values)

    def nth(self, index: int) -> "TextLocator":
        return TextLocator([self.values[index]])

    def inner_text(self) -> str:
        return self.values[0]


class MarketBox:
    def __init__(self, labels: list[str], odds: list[str]):
        self.labels = labels
        self.odds = odds

    def locator(self, selector: str) -> TextLocator:
        return TextLocator(self.labels if "OddLabel" in selector else self.odds)


class BoxList:
    def __init__(self, boxes: list[MarketBox]):
        self.boxes = boxes

    def count(self) -> int:
        return len(self.boxes)

    def nth(self, index: int) -> MarketBox:
        return self.boxes[index]


class CollapsedCard:
    def __init__(self) -> None:
        self.boxes = BoxList(
            [
                MarketBox(
                    ["Deportivo Cuenca", "Empate", "Manta"],
                    ["1.61", "3.60", "6.00"],
                ),
                MarketBox(["Más de 2.5", "Menos de 2.5"], ["2.40", "1.52"]),
            ]
        )

    def locator(self, _selector: str) -> BoxList:
        return self.boxes


class ModalLocator:
    def __init__(self, page: "BannerPage", is_close: bool = False):
        self.page = page
        self.is_close = is_close

    def count(self) -> int:
        return int(self.page.visible)

    @property
    def first(self) -> "ModalLocator":
        return self

    def click(self, timeout: int) -> None:
        assert timeout == 3000
        assert self.is_close
        self.page.visible = False


class BannerPage:
    def __init__(self) -> None:
        self.visible = True
        self.waits: list[int] = []

    def locator(self, selector: str) -> ModalLocator:
        return ModalLocator(self, is_close="label" in selector)

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def test_recurring_login_banner_is_closed_by_its_real_control() -> None:
    page = BannerPage()
    assert _dismiss_optional_login(page) is True
    assert page.visible is False
    assert page.waits == [250]


def test_collapsed_public_card_preserves_visible_real_odds() -> None:
    card = CollapsedCard()
    match = {"home": "Deportivo Cuenca", "away": "Manta"}

    one_x_two = _extract_collapsed_market(
        card,
        match,
        {"id": 1, "name": "1x2"},
        "2026-08-09T23:00:00-05:00",
    )
    total = _extract_collapsed_market(
        card,
        match,
        {"id": 2, "name": "Total de goles"},
        "2026-08-09T23:00:00-05:00",
    )

    assert [row["odd"] for row in one_x_two["data"]] == ["1.61", "3.60", "6.00"]
    assert [row["line"] for row in total["data"]] == ["2.5", "2.5"]
    assert [row["odd"] for row in total["data"]] == ["2.40", "1.52"]
    assert "TARJETA PÚBLICA" in total["coverage"]
