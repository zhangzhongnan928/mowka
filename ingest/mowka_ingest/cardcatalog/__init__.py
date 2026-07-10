"""Card catalog data (names, sets, numbers, images, USD reference) is
CONSUMED, never built. TCGdex and pokemontcg.io are both single-maintainer
projects; this adapter interface is the insurance — swapping providers must
never touch callers.

The USD market figure is a clearly-labeled REFERENCE ONLY: it is stored and
displayed separately and is never blended into the AU index or AU ranking.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CardInfo:
    ref: str
    name: str
    set_name: str
    set_code: str
    number: str
    image_url: str | None
    usd_market: float | None  # TCGplayer market price (reference only)
    source_url: str
    eur_market: float | None = None  # Cardmarket trend price (reference only)


class CardCatalogError(Exception):
    pass


def get_adapter(name: str = "tcgdex"):
    if name == "tcgdex":
        from .tcgdex import TcgdexCatalog
        return TcgdexCatalog()
    raise CardCatalogError(f"unknown card catalog adapter: {name}")
