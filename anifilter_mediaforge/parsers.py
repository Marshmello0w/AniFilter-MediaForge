"""Small dependency-free parsers for AniWorld's catalogue and release pages."""

from __future__ import annotations

import re
from datetime import date
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

BASE_URL = "https://aniworld.to"
_SERIES_RE = re.compile(r"^/anime/stream/([^/?#]+)(?:[/?#]|$)", re.I)
_EPISODE_RE = re.compile(
    r"^/anime/stream/([^/?#]+)/staffel-(\d+)/episode-(\d+)(?:[/?#]|$)", re.I
)
_DATE_RE = re.compile(r"(?:[A-ZÄÖÜa-zäöü]{2,3},\s*)?(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def slug_from_url(value: str) -> str | None:
    match = _SERIES_RE.match(urlparse(value).path)
    return match.group(1) if match else None


class _CatalogueParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.entries: dict[str, dict] = {}
        self.depth = 0
        self.genre_depth: int | None = None
        self.current_genre = ""
        self.in_h3 = False
        self.h3_text: list[str] = []
        self.anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "div":
            self.depth += 1
            classes = set((values.get("class") or "").split())
            if self.genre_depth is None and "genre" in classes:
                self.genre_depth = self.depth
                self.current_genre = ""
        elif tag == "h3" and self.genre_depth is not None:
            self.in_h3 = True
            self.h3_text = []
        elif tag == "a":
            href = values.get("href") or ""
            match = _SERIES_RE.match(urlparse(href).path)
            if match:
                self.anchor = {
                    "slug": match.group(1),
                    "href": href,
                    "text": [],
                    "aliases": [
                        _clean(part)
                        for part in (values.get("data-alternative-title") or "").split(",")
                        if _clean(part)
                    ],
                }

    def handle_data(self, data):
        if self.in_h3:
            self.h3_text.append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "h3" and self.in_h3:
            self.current_genre = _clean("".join(self.h3_text))
            self.in_h3 = False
        elif tag == "a" and self.anchor is not None:
            title = _clean("".join(self.anchor["text"]))
            slug = self.anchor["slug"]
            if title:
                row = self.entries.setdefault(
                    slug,
                    {
                        "slug": slug,
                        "title": title,
                        "aliases": [],
                        "genres": [],
                        "url": urljoin(self.base_url, self.anchor["href"]).rstrip("/"),
                    },
                )
                if not row["title"]:
                    row["title"] = title
                row["aliases"] = list(dict.fromkeys(row["aliases"] + self.anchor["aliases"]))
                if self.current_genre and self.current_genre not in row["genres"]:
                    row["genres"].append(self.current_genre)
            self.anchor = None
        elif tag == "div":
            if self.genre_depth == self.depth:
                self.genre_depth = None
                self.current_genre = ""
            self.depth = max(0, self.depth - 1)


def parse_catalogue(html: str, base_url: str = BASE_URL) -> list[dict]:
    parser = _CatalogueParser(base_url)
    parser.feed(html or "")
    return sorted(parser.entries.values(), key=lambda row: row["title"].casefold())


def merge_catalogues(*catalogues: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for catalogue in catalogues:
        for item in catalogue:
            existing = merged.get(item["slug"])
            if not existing:
                merged[item["slug"]] = {
                    **item,
                    "aliases": list(item.get("aliases") or []),
                    "genres": list(item.get("genres") or []),
                }
                continue
            existing["title"] = item.get("title") or existing["title"]
            existing["url"] = item.get("url") or existing["url"]
            existing["aliases"] = list(
                dict.fromkeys(existing["aliases"] + list(item.get("aliases") or []))
            )
            existing["genres"] = list(
                dict.fromkeys(existing["genres"] + list(item.get("genres") or []))
            )
    return sorted(merged.values(), key=lambda row: row["title"].casefold())


class _ReleaseParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.depth = 0
        self.row_depth: int | None = None
        self.rows: list[dict] = []
        self.row: dict | None = None
        self.in_h2 = False
        self.h2: list[str] = []
        self.in_strong = False
        self.in_date = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "div":
            self.depth += 1
            classes = set((values.get("class") or "").split())
            if self.row_depth is None and "col-md-12" in classes:
                self.row_depth = self.depth
                self.row = {"href": "", "title": [], "date": [], "german": False}
        elif tag == "h2":
            self.in_h2 = True
            self.h2 = []
        if self.row is None:
            return
        if tag == "a":
            href = values.get("href") or ""
            if _EPISODE_RE.match(urlparse(href).path):
                self.row["href"] = href
        elif tag == "img" and "flag" in (values.get("class") or "").split():
            source = values.get("data-src") or values.get("src") or ""
            if re.search(r"/german\.svg(?:[?#].*)?$", source, re.I):
                self.row["german"] = True
        elif tag == "strong":
            self.in_strong = True
        elif tag == "span" and "elementFloatRight" in (values.get("class") or "").split():
            self.in_date = True

    def handle_data(self, data):
        if self.in_h2:
            self.h2.append(data)
        if self.row is not None and self.in_strong:
            self.row["title"].append(data)
        if self.row is not None and self.in_date:
            self.row["date"].append(data)

    def handle_endtag(self, tag):
        if tag == "h2":
            self.in_h2 = False
        elif tag == "strong":
            self.in_strong = False
        elif tag == "span" and self.in_date:
            self.in_date = False
        elif tag == "div":
            if self.row_depth == self.depth and self.row is not None:
                self.rows.append(self.row)
                self.row = None
                self.row_depth = None
                self.in_strong = False
                self.in_date = False
            self.depth = max(0, self.depth - 1)


def _parse_date(value: str) -> str | None:
    match = _DATE_RE.search(value)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_german_releases(html: str, base_url: str = BASE_URL) -> list[dict]:
    parser = _ReleaseParser(base_url)
    parser.feed(html or "")
    declared_match = re.search(r"(\d+)\s+neuesten Episoden", _clean("".join(parser.h2)), re.I)
    declared = int(declared_match.group(1)) if declared_match else 0
    if declared < 20 or len(parser.rows) < int(declared * 0.8):
        raise ValueError("recent episodes page returned too few entries")

    newest: dict[str, dict] = {}
    for row in parser.rows:
        if not row["german"]:
            continue
        path = urlparse(row["href"]).path
        match = _EPISODE_RE.match(path)
        released_on = _parse_date(_clean("".join(row["date"])))
        title = _clean("".join(row["title"]))
        if not match or not released_on or not title:
            continue
        item = {
            "slug": match.group(1),
            "title": title,
            "season": int(match.group(2)),
            "episode": int(match.group(3)),
            "released_on": released_on,
            "episode_url": urljoin(base_url, row["href"]),
        }
        previous = newest.get(item["slug"])
        order = (item["released_on"], item["season"], item["episode"])
        old_order = (
            (previous["released_on"], previous["season"], previous["episode"])
            if previous
            else ("", -1, -1)
        )
        if order > old_order:
            newest[item["slug"]] = item
    return sorted(
        newest.values(),
        key=lambda item: (item["released_on"], item["season"], item["episode"]),
        reverse=True,
    )

