"""Build the scan-identify index: site/api/card-index.json.

Every English card's identity keys, from TCGdex. The printed collector
fraction ("161/131") is the primary identify key a scanner needs: the total
(131) selects candidate sets by their official card count, the numerator
selects the card — secret rares number above the official total but still
print "/131", so this works for them too.

Card data © TCGdex (https://tcgdex.dev) — consumed, not built; keep the
attribution field intact wherever this index is served or bundled.

Usage: python scripts/build_card_index.py [output.json]
~1 request per set (~150 requests), politely spaced. Run weekly via Actions.
"""
import json
import pathlib
import sys
import time
from datetime import datetime, timezone

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://api.tcgdex.net/v2/en"
UA = "MowkaAU/0.1 (+contact: zhangzhongnan928@gmail.com) card index build"
SPACING_SECONDS = 0.5


def build(session: requests.Session) -> dict:
    sets_resp = session.get(f"{BASE}/sets", timeout=30)
    sets_resp.raise_for_status()
    sets_meta = []
    cards = []
    for entry in sets_resp.json():
        set_id = entry["id"]
        detail_resp = session.get(f"{BASE}/sets/{set_id}", timeout=30)
        if detail_resp.status_code != 200:
            print(f"WARN skip set {set_id}: HTTP {detail_resp.status_code}")
            continue
        detail = detail_resp.json()
        counts = detail.get("cardCount") or {}
        sets_meta.append({
            "id": set_id,
            "name": detail.get("name", set_id),
            "official": counts.get("official"),
            "total": counts.get("total"),
        })
        for card in detail.get("cards") or []:
            cards.append([card["id"], card.get("localId", ""), card.get("name", "")])
        time.sleep(SPACING_SECONDS)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attribution": "Card data by TCGdex (https://tcgdex.dev). "
                       "Mowka consumes this catalog; it does not build it.",
        "sets": sets_meta,
        "cards": cards,  # [tcgdex id, localId, name]; set id = id up to last '-'
    }


def main() -> None:
    out_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                            else ROOT / "site" / "api" / "card-index.json")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    index = build(session)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, separators=(",", ":")) + "\n")
    print(f"{len(index['sets'])} sets, {len(index['cards'])} cards -> {out_path} "
          f"({out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
