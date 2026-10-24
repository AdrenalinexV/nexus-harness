"""Two plausible browser identities, tried in order.

Kept in a module of their own so the string literals sit in one place and `web.py` stays about
parsing. Any site that answers 403 to the first and 200 to the second is the reason there are two.
"""

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
)
