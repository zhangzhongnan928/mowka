from mowka_ingest.ranking import rank


def offer(price, in_stock=True, observed="2026-07-09T10:00:00+00:00", store="A"):
    return {"sku_id": "x", "store": store, "url": "u", "price_cents": price,
            "currency": "AUD", "in_stock": in_stock, "observed_at": observed}


def test_empty_returns_none():
    assert rank([]) is None


def test_lowest_in_stock_wins():
    best = rank([offer(9000), offer(8000), offer(10000)])
    assert best["price_cents"] == 8000


def test_in_stock_beats_cheaper_out_of_stock():
    best = rank([offer(5000, in_stock=False), offer(9000, in_stock=True)])
    assert best["price_cents"] == 9000 and best["in_stock"]


def test_all_out_of_stock_lowest_flagged():
    best = rank([offer(9000, in_stock=False), offer(7000, in_stock=False)])
    assert best["price_cents"] == 7000 and not best["in_stock"]


def test_price_tie_broken_by_freshest_observation():
    stale = offer(8000, observed="2026-07-01T00:00:00+00:00", store="Old")
    fresh = offer(8000, observed="2026-07-09T00:00:00+00:00", store="New")
    assert rank([stale, fresh])["store"] == "New"
    assert rank([fresh, stale])["store"] == "New"
