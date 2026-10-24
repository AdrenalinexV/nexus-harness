"""Reading the web without a browser: one page as text, or a short list of search results.

Anti-block here is not a proxy chain, it is three cheap things: a real browser UA, a second attempt
with a different UA and `Accept` when the first comes back 403/429, and a hard cap on what is returned.
A page that still refuses is reported as a refusal -- never as an empty success.
"""
import html
import re
import urllib.error
import urllib.parse
import urllib.request

from .http_ua import USER_AGENTS

MAX_TEXT = 9000
TIMEOUT = 25
STRIP_BLOCKS = re.compile(r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", re.S | re.I)
BLOCK_TAGS = re.compile(r"</?(p|div|br|li|tr|h[1-6]|section|article|pre|blockquote)\b[^>]*>", re.I)
ANY_TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"[ \t\u00a0]+")
BLANKS = re.compile(r"\n{3,}")
LINK = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


def _get(url, accept="text/html,application/xhtml+xml"):
    last = None
    for agent in USER_AGENTS:
        request = urllib.request.Request(url, headers={
            "User-Agent": agent, "Accept": accept, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                raw = response.read(4_000_000)
            return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code not in (403, 429, 503):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(getattr(exc, "reason", exc))
    raise ValueError("could not fetch %s (%s)" % (url, last or "no response"))


def to_text(markup):
    """The readable text of a page: blocks become lines, tags disappear, entities are decoded."""
    body = STRIP_BLOCKS.sub("", markup)
    body = BLOCK_TAGS.sub("\n", body)
    body = ANY_TAG.sub(" ", body)
    body = html.unescape(body)
    body = SPACES.sub(" ", body)
    lines = [line.strip() for line in body.split("\n")]
    return BLANKS.sub("\n\n", "\n".join(lines)).strip()


def fetch(url):
    markup = _get(str(url).strip())
    text = to_text(markup)
    clipped = text[:MAX_TEXT] + ("\n... (clipped)" if len(text) > MAX_TEXT else "")
    return clipped or "(the page had no readable text)", {"url": url, "chars": len(text),
                                                          "files": []}


def search(query, limit=8):
    """DuckDuckGo's no-JS endpoint: titles and links, nothing to parse twice."""
    target = "https://lite.duckduckgo.com/lite/?%s" % urllib.parse.urlencode({"q": query})
    markup = _get(target)
    rows, seen = [], set()
    for href, label in LINK.findall(markup):
        clean = urllib.parse.unquote(href)
        if "duckduckgo.com" in clean or clean in seen:
            continue
        seen.add(clean)
        title = to_text(label)[:120] or clean[:120]
        rows.append("- %s\n  %s" % (title, clean))
        if len(rows) >= int(limit):
            break
    if not rows:
        raise ValueError("the search endpoint returned no links (blocked or empty); try fetch on a "
                         "known URL instead")
    return "\n".join(rows), {"query": query, "results": len(rows), "files": []}


HANDLERS = {"fetch_url": lambda root, args, config: fetch(args.get("url", "")),
            "web_search": lambda root, args, config: search(args.get("query", ""),
                                                            args.get("limit", 8))}
