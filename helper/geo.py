"""Classifies a visitor into an ad-industry "GEO tier" (1-4) from their IP,
so /adsstats can show which quality of traffic is actually watching ads —
this is the standard Tier 1-4 breakdown ad networks (Monetag/Adsterra/etc.)
use for CPM, not "how many ad steps were shown."

Free, keyless lookup via ip-api.com (fine at this bot's scale — a few
requests per verification session, not per pageview). Results are cached
in-memory per IP for the life of the process to avoid refetching the same
visitor repeatedly and to survive that API's ~45 req/min rate limit.
"""

import aiohttp

# Approximate, commonly-used ad-industry GEO tiers. Tune freely — this is a
# simple set lookup, not a service, so editing this list is the whole job.
TIER_1 = {  # Highest CPM: US/Canada/UK/Western Europe/Australia/NZ/Japan
    "US", "CA", "GB", "AU", "NZ", "DE", "FR", "CH", "NO", "SE", "DK", "FI",
    "NL", "BE", "AT", "IE", "SG", "JP", "LU", "IS",
}
TIER_2 = {  # Mid-high: Southern/Eastern Europe, Gulf states, developed Asia
    "IT", "ES", "PT", "PL", "CZ", "GR", "HU", "SK", "SI", "EE", "LV", "LT",
    "HR", "IL", "AE", "SA", "QA", "KW", "BH", "OM", "MT", "CY", "HK", "TW",
    "KR", "MY",
}
TIER_3 = {  # Mid: large emerging markets
    "BR", "MX", "AR", "CL", "CO", "PE", "TR", "RU", "UA", "ZA", "TH", "VN",
    "PH", "ID", "IN", "EG", "MA", "TN", "KZ", "RS", "BA", "MK", "AL", "GE",
    "AM", "AZ", "RO", "BG",
}
# Everything else falls into Tier 4.

_cache: dict = {}  # ip -> (country_code, tier)


def _tier_for_country(country_code: str) -> int:
    if country_code in TIER_1:
        return 1
    if country_code in TIER_2:
        return 2
    if country_code in TIER_3:
        return 3
    return 4


def client_ip_from_request(request) -> str:
    """Best-effort real visitor IP, accounting for a reverse proxy (Heroku,
    nginx, Cloudflare, ...) in front of the aiohttp server."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote or ""


async def get_country_tier(ip: str) -> tuple:
    """Returns (country_code, tier). Defaults to ("XX", 4) on any failure —
    unknown traffic is treated as lowest tier rather than blocking anything."""
    if not ip or ip.startswith(("127.", "10.", "192.168.")) or ip == "::1":
        return "XX", 4
    if ip in _cache:
        return _cache[ip]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://ip-api.com/json/{ip}?fields=status,countryCode", timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json()
        if data.get("status") == "success" and data.get("countryCode"):
            country = data["countryCode"]
            result = (country, _tier_for_country(country))
        else:
            result = ("XX", 4)
    except Exception:
        result = ("XX", 4)

    if len(_cache) > 5000:  # bounded: a long-running process must not grow forever
        _cache.clear()
    _cache[ip] = result
    return result
