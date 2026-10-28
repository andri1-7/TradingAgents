"""Public IDX headline discovery. RSS metadata is not fetched article text."""
import re
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from tradingagents.dataflows.errors import VendorUnavailableError

FEED_URL = "https://news.google.com/rss/search"
# Deliberately curated, not an inferred issuer registry. BCA's official name:
# https://www.bca.co.id/en/tentang-bca
COMPANY_NAMES = {"BBCA.JK": "Bank Central Asia"}
MAX_BYTES = 1_048_576
MAX_ITEMS = 100
ARTICLE_LIMIT = 10
FETCH_SECONDS = 12


def get_idx_news(ticker: str, start_date: str, end_date: str) -> str:
    """Router boundary: an unavailable result must advance the vendor chain."""
    result = _get_idx_news(ticker, start_date, end_date)
    if result.startswith("<IDX news unavailable"):
        raise VendorUnavailableError(result)
    return result


def _get_idx_news(ticker: str, start_date: str, end_date: str) -> str:
    """Return public, dated headline metadata for canonical ``XXXX.JK``.

    Dates are inclusive calendar dates, restricted to the intersection of UTC
    and Jakarta windows and retrieval time. Search is not an archive and does
    not prove historical availability or exhaustive coverage.
    """
    unavailable = (
        f"<IDX news unavailable for {ticker} {start_date}..{end_date}: "
        "no qualifying dated RSS metadata; not evidence of no news>"
    )
    if not re.fullmatch(r"[A-Z]{4}\.JK", ticker):
        return "<IDX news unavailable: expected exact canonical four-letter IDX ticker XXXX.JK>"
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
        end = datetime.strptime(end_date, "%Y-%m-%d")
        if (start.strftime("%Y-%m-%d") != start_date
                or end.strftime("%Y-%m-%d") != end_date or start.date() > end.date()):
            raise ValueError("Invalid window")
        end_day = end + timedelta(days=1)
        before = (start - timedelta(days=1)).date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return "<IDX news unavailable: invalid YYYY-MM-DD date window>"
    retrieved = datetime.now(UTC)
    cutoff = min(end_day.replace(tzinfo=UTC),
                 end_day.replace(tzinfo=ZoneInfo("Asia/Jakarta")).astimezone(UTC), retrieved)
    code = ticker[:-3]
    company = COMPANY_NAMES.get(ticker)
    terms = f'("{code}" OR "{company}")' if company else f'"{code}"'
    query = f'{terms} Indonesia after:{before} before:{end_day.date().isoformat()}'
    response = None
    deadline = time.monotonic() + FETCH_SECONDS
    try:
        response = requests.get(
            FEED_URL, params={"q": query, "hl": "id", "gl": "ID", "ceid": "ID:id"},
            timeout=(3, 8), stream=True,
        )
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(chunk_size=16384):
            content.extend(chunk)
            if len(content) > MAX_BYTES or time.monotonic() > deadline:
                return unavailable.replace("no qualifying dated RSS metadata", "RSS retrieval budget exceeded")
        # No DTDs/entities: this provider needs only ordinary Google RSS fields.
        if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
            return unavailable
        root = ElementTree.fromstring(content)
    except (requests.RequestException, ElementTree.ParseError):
        return unavailable.replace("no qualifying dated RSS metadata", "public RSS request or parsing failed")
    finally:
        if response is not None:
            response.close()
    rows = []
    seen = set()
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        published = item.findtext("pubDate") or ""
        try:
            timestamp = parsedate_to_datetime(published)
            if timestamp.tzinfo is None:
                continue
            timestamp = timestamp.astimezone(UTC)
        except (ValueError, TypeError, OverflowError):
            continue
        if not start <= timestamp < cutoff:
            continue
        title = " ".join((item.findtext("title") or "").split())
        relevant = re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", title, re.I)
        if not relevant and not (company and company.casefold() in title.casefold()):
            continue
        link = (item.findtext("link") or "").strip()
        try:
            parsed = urlsplit(link)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
                continue
        except ValueError:
            continue
        key = (title.casefold(), link)
        if key in seen:
            continue
        seen.add(key)
        source = item.find("source")
        publisher = " ".join((source.text or "Unknown").split()) if source is not None else "Unknown"
        source_url = source.get("url", "") if source is not None else ""
        rows.append(
            f"### {title}\nPublished: {timestamp.isoformat()} (RSS: {published})\n"
            f"Link (RSS article URL; may be a Google News redirect): {link}\n"
            f"Publisher: {publisher}\nPublisher source URL (not article canonical URL): {source_url}\n"
        )
        if len(rows) >= ARTICLE_LIMIT:
            break
    if not rows:
        return unavailable
    return (
        f"## {ticker} News, {start_date}..{end_date} — RSS metadata only\n"
        f"Retrieved UTC: {retrieved.isoformat()}\n"
        f"Exclusive publication cutoff UTC: {cutoff.isoformat()}\n"
        "Headline discovery, not verified ticker tags. No full article text fetched; "
        "not an exhaustive archive or proof these metadata were available historically.\n\n"
        + "\n".join(rows)
    )
