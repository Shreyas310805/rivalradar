"""Internet Archive Wayback Machine client.

Wraps the CDX search API to find historical captures of any URL, and the
``web.archive.org/web/<timestamp>id_/<url>`` endpoint to download the original
archived bytes (``id_`` suppresses the Archive's own toolbar injection, which
would otherwise show up as a diff on every single page).

No site is hardcoded: every function takes a URL.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config.logging import get_logger
from app.config.settings import settings
from app.scrapers.url_guard import UnsafeURLError, validate_url

logger = get_logger(__name__)

WAYBACK_BASE = "https://web.archive.org/web"


class WaybackError(RuntimeError):
    """Raised when the Archive cannot serve a usable snapshot."""


@dataclass(slots=True)
class WaybackSnapshot:
    """One capture returned by the CDX API."""

    timestamp: str
    original_url: str
    status_code: str
    digest: str
    length: int = 0

    @property
    def archive_url(self) -> str:
        """URL that returns the raw archived bytes, toolbar-free."""
        return f"{WAYBACK_BASE}/{self.timestamp}id_/{self.original_url}"

    @property
    def viewer_url(self) -> str:
        """Human-browsable Archive URL."""
        return f"{WAYBACK_BASE}/{self.timestamp}/{self.original_url}"

    @property
    def date(self) -> datetime | None:
        """Parse the 14-digit CDX timestamp."""
        try:
            return datetime.strptime(self.timestamp, "%Y%m%d%H%M%S")
        except ValueError:
            return None

    @property
    def iso_date(self) -> str:
        parsed = self.date
        return parsed.strftime("%Y-%m-%d") if parsed else self.timestamp


def _to_cdx_timestamp(value: str | None) -> str | None:
    """Accept YYYY-MM-DD, YYYYMMDD or a full CDX timestamp."""
    if not value:
        return None
    cleaned = value.strip().replace("-", "").replace("/", "")
    if not cleaned.isdigit():
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD")
    if len(cleaned) not in (4, 6, 8, 14):
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD")
    return cleaned


def decode_archive_bytes(response: httpx.Response) -> str:
    """Decode archived bytes, preferring the document's own declared charset.

    Archived pages frequently lack a charset in the HTTP header, and httpx then
    guesses badly — producing mojibake that shows up as spurious diffs.  UTF-8
    is tried first, then the declared charset, then a lossy fallback.
    """
    raw = response.content
    if not raw:
        return ""

    candidates: list[str] = ["utf-8"]
    declared = response.charset_encoding
    if declared:
        candidates.append(declared)
    # <meta charset="..."> inside the first chunk of the document.
    head = raw[:4096].decode("ascii", errors="ignore").casefold()
    meta = re.search(r'charset=["\']?\s*([a-z0-9_\-]+)', head)
    if meta:
        candidates.append(meta.group(1))
    candidates.extend(["cp1252", "latin-1"])

    for encoding in dict.fromkeys(candidates):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def list_snapshots(
    url: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 40,
    status_filter: str = "200",
    timeout: float | None = None,
    newest_first: bool = False,
) -> list[WaybackSnapshot]:
    """Query the CDX API for captures of ``url``.

    Only successful captures are returned, and consecutive captures with an
    identical content digest are collapsed so a diff always compares genuinely
    different documents.

    ``newest_first`` uses CDX's negative-limit form to return the *last* N
    captures in the window rather than the first N.
    """
    timeout = settings.wayback_timeout_seconds if timeout is None else timeout

    try:
        target = validate_url(url)
    except UnsafeURLError as exc:
        raise WaybackError(f"unsafe target URL: {exc}") from exc

    params: dict[str, str | int] = {
        "url": target,
        "output": "json",
        "fl": "timestamp,original,statuscode,digest,length",
        "filter": f"statuscode:{status_filter}",
        "collapse": "digest",
        # A negative limit asks CDX for the LAST n rows of the window.
        "limit": -max(1, min(limit, 200)) if newest_first else max(1, min(limit, 200)),
    }
    start = _to_cdx_timestamp(from_date)
    end = _to_cdx_timestamp(to_date)
    if start:
        params["from"] = start
    if end:
        params["to"] = end

    rows: list | None = None
    last_error: Exception | None = None

    for attempt in range(3):
        try:
            response = httpx.get(
                settings.wayback_cdx_url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": settings.scan_user_agent},
                follow_redirects=True,
            )
            if response.status_code == 429:
                wait = 5.0 * (attempt + 1)
                logger.warning("Wayback rate limited; waiting %.0fs", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            rows = response.json()
            break
        except httpx.HTTPError as exc:
            last_error = exc
            wait = 2.0 * (attempt + 1)
            logger.warning("Wayback CDX request failed (%s); retrying in %.0fs", exc, wait)
            time.sleep(wait)
        except ValueError as exc:  # malformed JSON is not worth retrying
            last_error = exc
            break

    if rows is None:
        raise WaybackError(f"CDX API unavailable: {last_error}")

    if not rows or len(rows) < 2:
        logger.info("No Wayback snapshots found for %s", target)
        return []

    header, *records = rows
    index = {name: position for position, name in enumerate(header)}

    snapshots: list[WaybackSnapshot] = []
    for record in records:
        try:
            snapshots.append(
                WaybackSnapshot(
                    timestamp=record[index["timestamp"]],
                    original_url=record[index["original"]],
                    status_code=record[index["statuscode"]],
                    digest=record[index["digest"]],
                    length=int(record[index.get("length", 0)] or 0)
                    if "length" in index
                    else 0,
                )
            )
        except (IndexError, KeyError, ValueError):
            logger.debug("Skipping malformed CDX row: %r", record)

    snapshots.sort(key=lambda snap: snap.timestamp)
    logger.info("Found %d Wayback snapshots for %s", len(snapshots), target)
    return snapshots


def select_snapshot_pair(
    snapshots: list[WaybackSnapshot],
) -> tuple[WaybackSnapshot, WaybackSnapshot]:
    """Pick the two most useful captures to compare.

    The earliest and latest available captures are chosen: the widest time gap
    gives the most realistic mix of genuine changes and accumulated noise.
    """
    usable = [snap for snap in snapshots if snap.status_code == "200"] or snapshots
    # De-duplicate by digest so the pair is never two identical documents.
    seen: set[str] = set()
    distinct: list[WaybackSnapshot] = []
    for snap in sorted(usable, key=lambda s: s.timestamp):
        if snap.digest and snap.digest in seen:
            continue
        seen.add(snap.digest)
        distinct.append(snap)

    if len(distinct) < 2:
        raise WaybackError(
            f"need at least 2 distinct snapshots to compare, found {len(distinct)}"
        )
    return distinct[0], distinct[-1]


def list_snapshots_spread(
    url: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 40,
) -> list[WaybackSnapshot]:
    """Return captures from both ends of the window.

    CDX truncates from the start of the window, so a single ``limit=40`` query
    over a two-year range returns forty captures from the first few weeks.
    Querying both ends guarantees the evaluator compares documents that are
    genuinely far apart in time.
    """
    half = max(2, limit // 2)
    earliest = list_snapshots(url, from_date=from_date, to_date=to_date, limit=half)
    latest = list_snapshots(
        url, from_date=from_date, to_date=to_date, limit=half, newest_first=True
    )

    merged: dict[str, WaybackSnapshot] = {snap.timestamp: snap for snap in earliest}
    merged.update({snap.timestamp: snap for snap in latest})
    return sorted(merged.values(), key=lambda snap: snap.timestamp)


def download_snapshot(snapshot: WaybackSnapshot, *, timeout: float | None = None) -> str:
    """Download the archived HTML for one capture."""
    timeout = settings.wayback_timeout_seconds if timeout is None else timeout

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = httpx.get(
                snapshot.archive_url,
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": settings.scan_user_agent},
            )
            if response.status_code == 429:
                wait = 5.0 * (attempt + 1)
                logger.warning("Wayback rate limited on download; waiting %.0fs", wait)
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                raise WaybackError(
                    f"archive returned HTTP {response.status_code} for {snapshot.timestamp}"
                )
            html = decode_archive_bytes(response)
            if not html.strip():
                raise WaybackError(f"empty archived document for {snapshot.timestamp}")
            return html
        except WaybackError:
            raise
        except httpx.HTTPError as exc:
            last_error = exc
            wait = 2.0 * (attempt + 1)
            logger.warning("Archive download failed (%s); retrying in %.0fs", exc, wait)
            time.sleep(wait)

    raise WaybackError(f"could not download snapshot {snapshot.timestamp}: {last_error}")


def fetch_snapshot_pair(
    url: str,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 40,
) -> tuple[WaybackSnapshot, str, WaybackSnapshot, str]:
    """Find, select and download a comparable pair of captures.

    Returns ``(older, older_html, newer, newer_html)``.
    """
    snapshots = list_snapshots_spread(url, from_date=from_date, to_date=to_date, limit=limit)
    if not snapshots:
        raise WaybackError(f"no archived snapshots found for {url} in the requested window")

    older, newer = select_snapshot_pair(snapshots)
    logger.info(
        "Comparing Wayback captures %s -> %s for %s", older.iso_date, newer.iso_date, url
    )
    return older, download_snapshot(older), newer, download_snapshot(newer)
