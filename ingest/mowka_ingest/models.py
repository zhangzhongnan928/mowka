"""Core datatypes. Keep these boring and stable: everything else depends on them."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sku:
    id: str
    name: str
    set: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Offer:
    """One observed price for one SKU at one store at one moment."""
    sku_id: str
    store: str
    url: str
    price_cents: int
    currency: str
    in_stock: bool
    observed_at: str  # ISO 8601 UTC
