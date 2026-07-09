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
            category=s["category"], aliases=tuple(a.lower() for a in s.get("aliases", ())),
        )
        for s in raw["skus"]
    ]


def _clean(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().lower()


def match(title: str, catalog: list[Sku]) -> Sku | None:
    t = _clean(title)
    best: tuple[int, Sku] | None = None
    for sku in catalog:
        for alias in sku.aliases:
            if alias in t and (best is None or len(alias) > best[0]):
                best = (len(alias), sku)
    return best[1] if best else None
