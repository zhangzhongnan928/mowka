"""Map raw listing titles to canonical SKUs.

v0 rule: case-insensitive alias substring match, longest alias wins.
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


def _clean(title: str) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace. Punctuation
    varies wildly across listings ("161/131", "ETB - Prismatic", "Ultra-Premium");
    matching happens in punctuation-free space for both titles and aliases."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


# Listings whose title contains an alias but is NOT the English sealed product:
# graded slabs, foreign-language variants, empty/opened boxes. Proven pollution
# from live data (a PSA 9 graded card matched the Prismatic Evolutions ETB).
# Deliberately small and auditable; expand only with evidence.
EXCLUDE_TERMS = ("psa", "bgs", "cgc", "graded", "japanese", "korean", "chinese",
                 "empty box", "box only", "opened")


def match(title: str, catalog: list[Sku]) -> Sku | None:
    t = _clean(title)
    if any(term in t for term in EXCLUDE_TERMS):
        return None
    best: tuple[int, Sku] | None = None
    for sku in catalog:
        for alias in sku.aliases:
            if alias in t and (best is None or len(alias) > best[0]):
                best = (len(alias), sku)
    return best[1] if best else None
