"""Map raw listing titles to canonical SKUs.

v0 rule: case-insensitive alias match on token boundaries, longest alias wins.
Deliberately dumb and auditable. Fuzzy matching comes later, behind tests.
"""
import re
import yaml

from .models import Sku


def load_catalog(path: str) -> list[Sku]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return [
        Sku(
            id=s["id"], name=s["name"], set=s["set"],
            category=s["category"], aliases=tuple(_clean(a) for a in s.get("aliases", ())),
            kind=s.get("kind", "sealed"),
            catalog_ref=s.get("catalog_ref"), set_code=s.get("set_code"),
            number=s.get("number"), variant=s.get("variant"),
            language=s.get("language", "EN"),
        )
        for s in raw["skus"]
    ]


def _lower_collapse(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower()).strip()


def _clean(title: str) -> str:
    """Punctuation-free matching space: lowercase, drop currency amounts
    (a "$161" asking price must never look like card number 161), strip
    punctuation to spaces, collapse whitespace. Punctuation varies wildly
    across listings ("161/131", "ETB - Prismatic", "Ultra-Premium")."""
    no_prices = re.sub(r"[$€£]\s*\d+(?:[.,]\d+)?", " ", title.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", no_prices)).strip()


# Listings whose title contains an alias but is NOT a near-mint English
# product: graded slabs, foreign-language variants, empty/opened boxes,
# played-condition singles. Proven pollution from live data (a PSA 9 graded
# card matched the Prismatic Evolutions ETB). Deliberately small and
# auditable; expand only with evidence. Evaluated on the punctuation-PRESERVED
# title: "Booster Box - Only 2 left!" must not trip "box only".
EXCLUDE_TERMS = ("psa", "bgs", "cgc", "graded", "japanese", "korean", "chinese",
                 "empty box", "box only", "opened",
                 "damaged", "heavily played", "moderately played",
                 "lightly played", "creased")


def match(title: str, catalog: list[Sku]) -> Sku | None:
    if any(term in _lower_collapse(title) for term in EXCLUDE_TERMS):
        return None
    t = f" {_clean(title)} "
    best: tuple[int, Sku] | None = None
    for sku in catalog:
        for alias in sku.aliases:
            # token-boundary containment: alias "umbreon ex 161" must not
            # match "...umbreon ex 1610..." — numbers need a right edge
            if f" {alias} " in t and (best is None or len(alias) > best[0]):
                best = (len(alias), sku)
    return best[1] if best else None
