"""TCGdex adapter (https://api.tcgdex.net). Public API, no key required."""
import requests

from . import CardInfo

BASE = "https://api.tcgdex.net/v2/en"
UA = "MowkaAU/0.1 (+contact: zhangzhongnan928@gmail.com) card catalog sync"
# TCGplayer finish preference for the single reference figure we display
_FINISH_PRIORITY = ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil")


def _pricing_sources(payload: dict) -> list[dict]:
    """Modern cards carry pricing per variant; vintage cards (e.g. base1-4)
    carry it at the top level. Check variants first, then the top level."""
    sources = [(v.get("pricing") or {}) for v in payload.get("variants_detailed") or []]
    sources.append(payload.get("pricing") or {})
    return sources


def _usd_market(payload: dict) -> float | None:
    for finish in _FINISH_PRIORITY:
        for pricing in _pricing_sources(payload):
            market = ((pricing.get("tcgplayer") or {}).get(finish) or {}).get("marketPrice")
            if market:
                return float(market)
    return None


def _eur_market(payload: dict) -> float | None:
    """Cardmarket pricing is flat (no finish sub-keys): prefer trend, fall
    back to the 30-day average."""
    for pricing in _pricing_sources(payload):
        cardmarket = pricing.get("cardmarket") or {}
        for key in ("trend", "avg30"):
            if cardmarket.get(key):
                return float(cardmarket[key])
    return None


class TcgdexCatalog:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = UA

    def card(self, ref: str) -> CardInfo | None:
        resp = self.session.get(f"{BASE}/cards/{ref}", timeout=20)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        d = resp.json()
        image = d.get("image")
        return CardInfo(
            ref=ref,
            name=d["name"],
            set_name=d["set"]["name"],
            set_code=d["set"]["id"],
            number=d.get("localId", ""),
            image_url=f"{image}/low.webp" if image else None,
            usd_market=_usd_market(d),
            source_url=f"{BASE}/cards/{ref}",
            eur_market=_eur_market(d),
        )
