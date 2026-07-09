"""THE RANKING RULE (public, verifiable, no exceptions):

  best offer = lowest price among in-stock offers;
  if nothing is in stock, lowest price overall, flagged out of stock;
  ties broken by most recent observation.

Any first-party store Mowka ever operates ranks under this same function.
Lives here so the site exporter and the cron snapshot share one implementation.
"""


def rank(offers: list[dict]) -> dict | None:
    if not offers:
        return None
    in_stock = [o for o in offers if o["in_stock"]]
    pool = in_stock or offers
    # Stable sort: freshest first, then by price — equal prices keep freshest first.
    freshest_first = sorted(pool, key=lambda o: o["observed_at"], reverse=True)
    return sorted(freshest_first, key=lambda o: o["price_cents"])[0]
