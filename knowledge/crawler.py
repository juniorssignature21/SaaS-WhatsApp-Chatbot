"""Crawl a small website (same host, breadth-first) into one knowledge document."""

import logging
from collections import deque
from urllib.parse import urldefrag, urlparse
from urllib.robotparser import RobotFileParser

from common.netsafety import UnsafeURLError

from .loaders import USER_AGENT, LoaderError, fetch, fetch_page

logger = logging.getLogger(__name__)

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js", ".zip", ".mp4", ".mp3",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def _robots(start_url):
    parsed = urlparse(start_url)
    parser = RobotFileParser()
    try:
        _, response = fetch(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        parser.parse(response.text.splitlines())
    except (LoaderError, UnsafeURLError):
        parser.parse([])  # no robots.txt: everything allowed
    return parser


def _normalise(url):
    url = urldefrag(url)[0]
    return url[:-1] if url.endswith("/") and urlparse(url).path not in {"", "/"} else url


def crawl(start_url, max_pages):
    """Return text of up to ``max_pages`` pages on the start URL's host, with page headers."""
    host = urlparse(start_url).netloc
    robots = _robots(start_url)
    queue, seen, pages = deque([_normalise(start_url)]), {_normalise(start_url)}, []
    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if not robots.can_fetch(USER_AGENT, url):
            continue
        try:
            final_url, text, links = fetch_page(url)
        except (LoaderError, UnsafeURLError) as exc:
            if not pages and url == _normalise(start_url):
                raise LoaderError(str(exc)) from exc
            logger.info("Skipping %s: %s", url, exc)
            continue
        if text.strip():
            pages.append(f"Page: {final_url}\n\n{text.strip()}")
        for link in links:
            link = _normalise(link)
            parsed = urlparse(link)
            if (parsed.scheme in {"http", "https"} and parsed.netloc == host and link not in seen
                    and not parsed.path.lower().endswith(SKIP_EXTENSIONS)):
                seen.add(link)
                queue.append(link)
    return "\n\n".join(pages)
