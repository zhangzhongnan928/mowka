"""Core datatypes. Keep these boring and stable: everything else depends on them."""
from dataclasses import dataclass, field

SKU_KINDS = ("sealed", "card")
SOURCE_TYPES = ("store_shopify", "ebay_active", "ebay_sold")


@dataclass(frozen=True)
class Sku:
    id: str
    name: str
    set: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    kind: str = "sealed"
    # card-only fields (kind == "card"); sealed SKUs leave them at defaults
    catalog_ref: str | None = None  # external card-catalog id, e.g. TCGdex "sv08.5-161"
    set_code: str | None = None
    number: str | None = None
    variant: str | None = None      # e.g. holo, reverse, special-illustration-rare
    language: str = "EN"


@dataclass(frozen=True)
class Offer:
    """One observed price for one SKU at one source at one moment."""
    sku_id: str
    store: str
    url: str
    price_cents: int
    currency: str
    in_stock: bool
    observed_at: str  # ISO 8601 UTC
    source_type: str = "store_shopify"
