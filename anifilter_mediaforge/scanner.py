from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from urllib.parse import urlparse

from .db import Store
from .parsers import BASE_URL, merge_catalogues, parse_catalogue, parse_german_releases, slug_from_url

_worker = None
_worker_lock = threading.Lock()


def is_supported_aniworld_series_url(value):
    try:
        parsed = urlparse(str(value))
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"aniworld.to", "www.aniworld.to"}:
        return False
    if parsed.query or parsed.fragment:
        return False
    parts = parsed.path.rstrip("/").split("/")
    if len(parts) != 4 or parts[:3] != ["", "anime", "stream"] or not parts[3]:
        return False
    return all(character.isascii() and (character.isalnum() or character in "-_") for character in parts[3])


class RateGate:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.pause_until = 0.0

    def wait(self, interval: float, stop: threading.Event):
        while not stop.is_set():
            with self.lock:
                now = time.monotonic()
                target = max(self.next_at, self.pause_until)
                delay = max(0.0, target - now)
                if delay <= 0:
                    self.next_at = now + interval
                    return
            stop.wait(min(delay, 1.0))

    def cooldown(self, seconds: float):
        with self.lock:
            self.pause_until = max(self.pause_until, time.monotonic() + seconds)


class Scanner:
    PROFILES = {
        "gentle": (1, 1.0),
        "normal": (2, 0.55),
        "fast": (3, 0.35),
    }

    def __init__(self, app):
        self.app = app
        self.store = Store()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = None
        self.force_catalogue = False
        self.force_details = False
        self.gate = RateGate()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.store.initialize()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name="anifilter-scanner", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def request_refresh(self, force_details=False):
        self.force_catalogue = True
        self.force_details = self.force_details or force_details
        self.wake_event.set()

    @staticmethod
    def _due(value: str, hours: int) -> bool:
        if not value:
            return True
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            return datetime.now().astimezone() - stamp >= timedelta(hours=hours)
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _retry_ready(value: str) -> bool:
        if not value:
            return True
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            return datetime.now().astimezone() >= stamp
        except (TypeError, ValueError):
            return True

    def _refresh_due(self, kind: str, hours: int) -> bool:
        return self._retry_ready(self.store.get_state(f"{kind}_next_retry_at")) and self._due(
            self.store.get_state(f"{kind}_updated_at"), hours
        )

    def _speed(self):
        try:
            from ...db import get_setting
            from . import SPEED_KEY

            selected = get_setting(SPEED_KEY, "normal")
        except Exception:
            selected = "normal"
        return self.PROFILES.get(selected, self.PROFILES["normal"])

    def _http_get(self, url: str) -> str:
        from ....config import GLOBAL_SESSION

        response = GLOBAL_SESSION.get(url, timeout=45)
        response.raise_for_status()
        return response.text

    def refresh_catalogue(self):
        alphabet = []
        try:
            from ... import catalogue_store

            rows, _meta = catalogue_store.get_entries("aniworld", force=False)
            for row in rows or []:
                slug = slug_from_url(row.get("url") or "")
                if slug:
                    alphabet.append(
                        {
                            "slug": slug, "title": row.get("title") or slug,
                            "aliases": [v.strip() for v in (row.get("alt") or "").split(",") if v.strip()],
                            "genres": [], "url": (row.get("url") or "").rstrip("/"),
                        }
                    )
        except Exception:
            self.app.logger.debug("[AniFilter] MediaForge catalogue not ready", exc_info=True)

        genre_catalogue = parse_catalogue(self._http_get(f"{BASE_URL}/animes"), BASE_URL)
        if len(alphabet) < 100:
            alphabet = parse_catalogue(self._http_get(f"{BASE_URL}/animes-alphabet"), BASE_URL)
        if len(genre_catalogue) < 100 or len(alphabet) < 100:
            raise ValueError("AniWorld catalogue response was empty or truncated")
        merged = merge_catalogues(genre_catalogue, alphabet)
        previous = self.store.active_count()
        if previous >= 100 and len(merged) < int(previous * 0.75):
            raise ValueError("AniWorld catalogue shrank implausibly; keeping the previous snapshot")
        self.store.upsert_catalogue(merged)
        if self.force_details:
            with self.store.connect() as db:
                db.execute("UPDATE anime SET scan_status='pending' WHERE active=1")
        self.force_catalogue = False
        self.force_details = False

    def refresh_releases(self):
        releases = parse_german_releases(self._http_get(f"{BASE_URL}/neue-episoden"), BASE_URL)
        self.store.save_releases(releases)

    def scan_one(self, item, interval):
        if self.stop_event.is_set():
            return
        self.gate.wait(interval, self.stop_event)
        try:
            from ....models.aniworld_to.series import AniworldSeries

            class AniFilterSeries(AniworldSeries):
                is_valid_aniworld_series_url = staticmethod(is_supported_aniworld_series_url)

            series = AniFilterSeries(url=item["url"])
            title = series.title
            if not title:
                raise ValueError(getattr(series, "page_problem", None) or "AniWorld detail page has no title")
            self.store.save_detail(
                item["slug"],
                {
                    "title": title,
                    "description": series.description,
                    "poster_url": series.poster_url,
                    "release_year": series.release_year,
                    "age_rating": series.age_rating,
                    "rating": series.rating,
                    "directors": series.directors,
                    "actors": series.actors,
                    "producer": series.producer,
                    "country": series.country,
                    "genres": series.genres,
                },
            )
        except Exception as exc:
            message = str(exc)
            self.store.mark_scan_error(item["slug"], message)
            lowered = message.casefold()
            if "429" in lowered or "rate" in lowered or "too many" in lowered or "bot check" in lowered:
                self.gate.cooldown(300)
            self.app.logger.warning("[AniFilter] detail %s failed: %s", item["slug"], message)

    def _report(self, mode="idle", detail=""):
        try:
            from ... import worker_registry as wr

            status = self.store.status()
            extra = {
                "found": status["found"], "completed": status["completed"],
                "pending": status["pending"], "errors": status["errors"],
            }
            if mode == "working":
                wr.working("anifilter_mediaforge", detail=detail, extra=extra)
            elif mode == "error":
                wr.fail("anifilter_mediaforge", detail, extra=extra)
            else:
                wr.idle("anifilter_mediaforge", extra=extra)
        except Exception:
            pass

    def run(self):
        self._report("idle")
        while not self.stop_event.is_set():
            try:
                forced = self.force_catalogue
                if forced or self._refresh_due("catalogue", 24):
                    self.force_catalogue = False
                    self._report("working", "Katalog wird aktualisiert")
                    try:
                        self.refresh_catalogue()
                    except Exception as exc:
                        self.store.mark_refresh_error("catalogue", str(exc))
                        self.app.logger.warning("[AniFilter] catalogue refresh failed: %s", exc)

                if self._refresh_due("releases", 1):
                    try:
                        self.refresh_releases()
                    except Exception as exc:
                        self.store.mark_refresh_error("releases", str(exc))
                        self.app.logger.warning("[AniFilter] release refresh failed: %s", exc)

                concurrency, interval = self._speed()
                batch = []
                for _ in range(concurrency):
                    item = self.store.next_scan_item()
                    if item:
                        batch.append(item)
                if batch:
                    status = self.store.status()
                    self._report("working", f"Details {status['completed']}/{status['found']}")
                    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="anifilter-detail") as pool:
                        futures = [pool.submit(self.scan_one, item, interval) for item in batch]
                        wait(futures)
                    continue
                self._report("idle")
            except Exception as exc:
                self._report("error", str(exc))
                self.app.logger.exception("[AniFilter] scanner loop failed")

            self.wake_event.wait(30)
            self.wake_event.clear()


def start_worker(app):
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = Scanner(app)
        _worker.start()


def stop_worker(app):
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def request_refresh(force_details=False):
    with _worker_lock:
        if _worker is None:
            return False
        _worker.request_refresh(force_details=force_details)
        return True
