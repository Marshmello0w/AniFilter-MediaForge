from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PARSER_VERSION = 1
_CANONICAL_FSK_LEVELS = {0, 6, 12, 16, 18}
try:
    _BERLIN = ZoneInfo("Europe/Berlin")
except ZoneInfoNotFoundError:
    _BERLIN = datetime.now().astimezone().tzinfo


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now() -> str:
    return datetime.now(tz=_BERLIN).isoformat(timespec="seconds")


def _json(value) -> str:
    return json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))


def _loads(value, default=None):
    try:
        return json.loads(value) if value else (default if default is not None else [])
    except (TypeError, ValueError):
        return default if default is not None else []


def normalize_poster_url(value) -> str:
    raw = str(value or "").strip()
    if not raw or raw.startswith("data:"):
        return ""
    if raw.startswith("/api/img?"):
        return raw
    second_http = min(
        (pos for pos in (raw.find("https://", 8), raw.find("http://", 7)) if pos >= 0),
        default=-1,
    )
    if second_http >= 0:
        raw = raw[second_http:]
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("/"):
        return urljoin("https://aniworld.to/", raw)
    if raw.startswith(("https://", "http://")):
        return raw
    return ""


def default_db_path() -> Path:
    try:
        from ..registry import module_data_dir

        return module_data_dir("anifilter_mediaforge") / "anifilter.sqlite"
    except Exception:
        return Path.home() / ".mediaforge" / "module_data" / "anifilter_mediaforge" / "anifilter.sqlite"


class Store:
    _init_lock = threading.Lock()

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, factory=_ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self._init_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS anime (
                        slug TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        aliases_json TEXT NOT NULL DEFAULT '[]',
                        catalogue_genres_json TEXT NOT NULL DEFAULT '[]',
                        genres_json TEXT NOT NULL DEFAULT '[]',
                        description TEXT NOT NULL DEFAULT '',
                        poster_url TEXT NOT NULL DEFAULT '',
                        release_year TEXT NOT NULL DEFAULT '',
                        age_rating INTEGER,
                        rating TEXT NOT NULL DEFAULT '',
                        directors_json TEXT NOT NULL DEFAULT '[]',
                        actors_json TEXT NOT NULL DEFAULT '[]',
                        producer TEXT NOT NULL DEFAULT '',
                        country TEXT NOT NULL DEFAULT '',
                        parser_version INTEGER NOT NULL DEFAULT 0,
                        scan_status TEXT NOT NULL DEFAULT 'pending',
                        error_count INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT NOT NULL DEFAULT '',
                        next_retry_at TEXT,
                        active INTEGER NOT NULL DEFAULT 1,
                        missing_count INTEGER NOT NULL DEFAULT 0,
                        discovered_at TEXT NOT NULL,
                        last_scanned_at TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_anime_active ON anime(active, title);
                    CREATE INDEX IF NOT EXISTS idx_anime_scan ON anime(active, scan_status, next_retry_at);
                    CREATE TABLE IF NOT EXISTS german_releases (
                        anime_slug TEXT PRIMARY KEY REFERENCES anime(slug) ON DELETE CASCADE,
                        released_on TEXT NOT NULL,
                        season INTEGER NOT NULL,
                        episode INTEGER NOT NULL,
                        episode_url TEXT NOT NULL,
                        seen_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_releases_date ON german_releases(released_on DESC);
                    """
                )
                db.execute("UPDATE anime SET scan_status='pending' WHERE scan_status='in_progress'")
                migration = db.execute(
                    "SELECT value FROM state WHERE key='underscore_url_fix_version'"
                ).fetchone()
                if not migration or migration["value"] != "1":
                    db.execute(
                        """UPDATE anime SET scan_status='pending',error_count=0,last_error='',
                           next_retry_at=NULL WHERE scan_status='error' AND instr(slug,'_')>0
                           AND last_error LIKE 'Invalid AniWorld series URL:%'"""
                    )
                    db.execute(
                        "INSERT INTO state(key,value) VALUES('underscore_url_fix_version','1') "
                        "ON CONFLICT(key) DO UPDATE SET value='1'"
                    )

    def mark_refresh_error(self, kind: str, message: str) -> str:
        if kind not in {"catalogue", "releases"}:
            raise ValueError("unknown refresh kind")
        now = datetime.now(tz=_BERLIN)
        count_key = f"{kind}_error_count"
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (count_key,)).fetchone()
            try:
                count = int(row["value"] if row else 0) + 1
            except (TypeError, ValueError):
                count = 1
            delay_minutes = min(6 * 60, 5 * (2 ** min(count - 1, 8)))
            retry_at = (now + timedelta(minutes=delay_minutes)).isoformat(timespec="seconds")
            values = {
                f"{kind}_error": str(message)[:500],
                count_key: count,
                f"{kind}_last_attempt_at": now.isoformat(timespec="seconds"),
                f"{kind}_next_retry_at": retry_at,
            }
            for key, value in values.items():
                db.execute(
                    "INSERT INTO state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value)),
                )
        return retry_at

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_state(self, key: str, value) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def active_count(self) -> int:
        with self.connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM anime WHERE active=1").fetchone()[0])

    def upsert_catalogue(self, entries: list[dict]) -> int:
        if len(entries) < 100:
            raise ValueError("catalogue returned too few entries")
        now = _now()
        slugs = {row["slug"] for row in entries}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in entries:
                existing = db.execute(
                    "SELECT parser_version,genres_json FROM anime WHERE slug=?", (row["slug"],)
                ).fetchone()
                catalogue_genres = list(dict.fromkeys(row.get("genres") or []))
                aliases = list(dict.fromkeys(row.get("aliases") or []))
                if existing:
                    status_sql = (
                        ", scan_status='pending'" if int(existing["parser_version"] or 0) < PARSER_VERSION else ""
                    )
                    genres = _loads(existing["genres_json"])
                    if not genres:
                        genres = catalogue_genres
                    db.execute(
                        f"""UPDATE anime SET url=?,title=?,aliases_json=?,catalogue_genres_json=?,
                            genres_json=?,active=1,missing_count=0,updated_at=? {status_sql}
                            WHERE slug=?""",
                        (
                            row["url"],
                            row["title"],
                            _json(aliases),
                            _json(catalogue_genres),
                            _json(genres),
                            now,
                            row["slug"],
                        ),
                    )
                else:
                    db.execute(
                        """INSERT INTO anime(
                            slug,url,title,aliases_json,catalogue_genres_json,genres_json,
                            discovered_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?)""",
                        (
                            row["slug"], row["url"], row["title"], _json(aliases),
                            _json(catalogue_genres), _json(catalogue_genres), now, now,
                        ),
                    )

            current = db.execute("SELECT slug FROM anime WHERE active=1").fetchall()
            for item in current:
                if item["slug"] not in slugs:
                    db.execute(
                        "UPDATE anime SET missing_count=missing_count+1,updated_at=? WHERE slug=?",
                        (now, item["slug"]),
                    )
            db.execute("UPDATE anime SET active=0 WHERE missing_count>=3")
            db.execute(
                "INSERT INTO state(key,value) VALUES('catalogue_updated_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            db.execute(
                "INSERT INTO state(key,value) VALUES('catalogue_error','') "
                "ON CONFLICT(key) DO UPDATE SET value=''"
            )
            for key, value in (
                ("catalogue_error_count", "0"),
                ("catalogue_next_retry_at", ""),
                ("catalogue_last_attempt_at", now),
            ):
                db.execute(
                    "INSERT INTO state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
            db.commit()
        return len(entries)

    def next_scan_item(self) -> dict | None:
        now = _now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM anime
                   WHERE active=1 AND (
                     scan_status='pending' OR (scan_status='done' AND parser_version<?) OR
                     (scan_status='error' AND (next_retry_at IS NULL OR next_retry_at<=?))
                   )
                   ORDER BY CASE WHEN scan_status='pending' OR
                            (scan_status='done' AND parser_version<?) THEN 0 ELSE 1 END,
                            error_count, discovered_at, slug
                   LIMIT 1""",
                (PARSER_VERSION, now, PARSER_VERSION),
            ).fetchone()
            if not row:
                db.commit()
                return None
            db.execute("UPDATE anime SET scan_status='in_progress' WHERE slug=?", (row["slug"],))
            db.commit()
            return dict(row)

    def save_detail(self, slug: str, detail: dict) -> None:
        genres = list(dict.fromkeys(str(v).strip() for v in detail.get("genres") or [] if str(v).strip()))
        age = detail.get("age_rating")
        try:
            age = int(age) if age not in (None, "") else None
        except (TypeError, ValueError):
            age = None
        with self.connect() as db:
            db.execute(
                """UPDATE anime SET title=?,description=?,poster_url=?,release_year=?,age_rating=?,
                   rating=?,directors_json=?,actors_json=?,producer=?,country=?,genres_json=?,
                   parser_version=?,scan_status='done',error_count=0,last_error='',next_retry_at=NULL,
                   last_scanned_at=?,updated_at=? WHERE slug=?""",
                (
                    detail.get("title") or slug,
                    detail.get("description") or "",
                    normalize_poster_url(detail.get("poster_url")),
                    detail.get("release_year") or "",
                    age,
                    detail.get("rating") or "",
                    _json(detail.get("directors")),
                    _json(detail.get("actors")),
                    detail.get("producer") or "",
                    detail.get("country") or "",
                    _json(genres),
                    PARSER_VERSION,
                    _now(),
                    _now(),
                    slug,
                ),
            )

    def mark_scan_error(self, slug: str, message: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT error_count FROM anime WHERE slug=?", (slug,)).fetchone()
            count = int(row["error_count"] if row else 0) + 1
            minutes = min(24 * 60, 5 * (2 ** min(count - 1, 8)))
            retry = (datetime.now(tz=_BERLIN) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            db.execute(
                """UPDATE anime SET scan_status='error',error_count=?,last_error=?,
                   next_retry_at=?,updated_at=? WHERE slug=?""",
                (count, str(message)[:500], retry, _now(), slug),
            )

    def save_releases(self, releases: list[dict]) -> int:
        saved = 0
        now = _now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in releases:
                row = db.execute("SELECT genres_json FROM anime WHERE slug=? AND active=1", (item["slug"],)).fetchone()
                if not row:
                    continue
                existing = db.execute(
                    "SELECT released_on,season,episode FROM german_releases WHERE anime_slug=?",
                    (item["slug"],),
                ).fetchone()
                new_order = (item["released_on"], int(item["season"]), int(item["episode"]))
                old_order = (
                    (existing["released_on"], int(existing["season"]), int(existing["episode"]))
                    if existing else ("", -1, -1)
                )
                if new_order >= old_order:
                    db.execute(
                        """INSERT INTO german_releases(
                            anime_slug,released_on,season,episode,episode_url,seen_at
                        ) VALUES(?,?,?,?,?,?) ON CONFLICT(anime_slug) DO UPDATE SET
                            released_on=excluded.released_on,season=excluded.season,
                            episode=excluded.episode,episode_url=excluded.episode_url,
                            seen_at=excluded.seen_at""",
                        (
                            item["slug"], item["released_on"], int(item["season"]),
                            int(item["episode"]), item["episode_url"], now,
                        ),
                    )
                    saved += 1
                genres = _loads(row["genres_json"])
                if "Ger" not in genres:
                    genres.append("Ger")
                    db.execute(
                        "UPDATE anime SET genres_json=?,updated_at=? WHERE slug=?",
                        (_json(genres), now, item["slug"]),
                    )
            db.execute(
                "INSERT INTO state(key,value) VALUES('releases_updated_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            db.execute(
                "INSERT INTO state(key,value) VALUES('releases_error','') "
                "ON CONFLICT(key) DO UPDATE SET value=''"
            )
            for key, value in (
                ("releases_error_count", "0"),
                ("releases_next_retry_at", ""),
                ("releases_last_attempt_at", now),
            ):
                db.execute(
                    "INSERT INTO state(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
            db.commit()
        return saved

    def get_anime(self, slug: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM anime WHERE slug=? AND active=1", (slug,)).fetchone()
        return self._project(row) if row else None

    @staticmethod
    def _project(row) -> dict:
        return {
            "slug": row["slug"],
            "url": row["url"],
            "title": row["title"],
            "aliases": _loads(row["aliases_json"]),
            "genres": _loads(row["genres_json"]),
            "description": row["description"],
            "poster_url": normalize_poster_url(row["poster_url"]),
            "release_year": row["release_year"],
            "age_rating": row["age_rating"],
            "rating": row["rating"],
            "directors": _loads(row["directors_json"]),
            "actors": _loads(row["actors_json"]),
            "producer": row["producer"],
            "country": row["country"],
            "scan_status": row["scan_status"],
            "last_scanned_at": row["last_scanned_at"],
        }

    def catalogue(self, filters: dict, age_ceiling: int | None = None) -> dict:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM anime WHERE active=1").fetchall()
        all_items = [self._project(row) for row in rows]
        genres = sorted({genre for item in all_items for genre in item["genres"]}, key=str.casefold)
        ages = {
            int(item["age_rating"]) for item in all_items if item["age_rating"] is not None
        } | _CANONICAL_FSK_LEVELS
        if age_ceiling is not None:
            ages = {age for age in ages if age <= age_ceiling}
        ages = sorted(ages)

        query = str(filters.get("q") or "").strip().casefold()
        include = {str(v).casefold() for v in filters.get("include") or []}
        exclude = {str(v).casefold() for v in filters.get("exclude") or []}
        genre_mode = filters.get("genre_mode") if filters.get("genre_mode") in ("all", "any") else "all"
        age_mode = filters.get("age_mode") if filters.get("age_mode") in ("all", "exact", "max") else "all"
        exact_ages = {int(v) for v in filters.get("ages") or [] if str(v).isdigit()}
        max_age = int(filters["age_max"]) if str(filters.get("age_max") or "").isdigit() else None

        def keep(item):
            haystack = " ".join([item["title"], *item["aliases"]]).casefold()
            if query and query not in haystack:
                return False
            item_genres = {str(v).casefold() for v in item["genres"]}
            if exclude & item_genres:
                return False
            if include and genre_mode == "all" and not include.issubset(item_genres):
                return False
            if include and genre_mode == "any" and not (include & item_genres):
                return False
            age = item["age_rating"]
            if age_ceiling is not None and age is not None and int(age) > age_ceiling:
                return False
            if age_mode == "exact" and exact_ages and (age is None or int(age) not in exact_ages):
                return False
            if age_mode == "max" and max_age is not None and (age is None or int(age) > max_age):
                return False
            return True

        found = [item for item in all_items if keep(item)]
        sort = filters.get("sort") or "title_asc"
        if sort == "title_desc":
            found.sort(key=lambda item: item["title"].casefold(), reverse=True)
        elif sort in ("year_desc", "year_asc"):
            found.sort(
                key=lambda item: (self._year(item["release_year"]), item["title"].casefold()),
                reverse=sort == "year_desc",
            )
        elif sort == "updated_desc":
            found.sort(key=lambda item: item.get("last_scanned_at") or "", reverse=True)
        else:
            found.sort(key=lambda item: item["title"].casefold())

        page = max(1, int(filters.get("page") or 1))
        per_page = min(96, max(12, int(filters.get("per_page") or 36)))
        total = len(found)
        pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, pages)
        start = (page - 1) * per_page
        return {
            "items": found[start:start + per_page],
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": per_page,
            "facets": {"genres": genres, "ages": ages},
        }

    @staticmethod
    def _year(value: str) -> int:
        try:
            return int(str(value).split("-", 1)[0])
        except (TypeError, ValueError):
            return 0

    def german_releases(self, limit: int = 6, reference: date | None = None) -> dict:
        today = reference or datetime.now(tz=_BERLIN).date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        year_start = today.replace(month=1, day=1)
        with self.connect() as db:
            rows = db.execute(
                """SELECT r.*,a.title,a.url,a.poster_url,a.age_rating,a.genres_json
                   FROM german_releases r JOIN anime a ON a.slug=r.anime_slug
                   WHERE a.active=1 ORDER BY r.released_on DESC,r.season DESC,r.episode DESC"""
            ).fetchall()

        groups = {"week": [], "month": [], "year": [], "older": []}
        labels = {
            "week": "Diese Woche", "month": "Diesen Monat",
            "year": "Dieses Jahr", "older": "Früher",
        }
        for row in rows:
            released = date.fromisoformat(row["released_on"])
            group = "week" if released >= week_start else "month" if released >= month_start else "year" if released >= year_start else "older"
            groups[group].append(
                {
                    "slug": row["anime_slug"], "title": row["title"], "url": row["url"],
                    "poster_url": row["poster_url"], "age_rating": row["age_rating"],
                    "genres": _loads(row["genres_json"]), "released_on": row["released_on"],
                    "season": row["season"], "episode": row["episode"],
                    "episode_url": row["episode_url"], "group": group,
                    "period_label": labels[group],
                }
            )
        ordered = []
        for group in ("week", "month", "year", "older"):
            ordered.extend(groups[group])
            if len(ordered) >= limit:
                break
        return {
            "items": ordered[:limit],
            "updated_at": self.get_state("releases_updated_at"),
            "last_error": self.get_state("releases_error"),
        }

    def status(self) -> dict:
        with self.connect() as db:
            counts = {
                row["scan_status"]: int(row["count"])
                for row in db.execute(
                    "SELECT scan_status,COUNT(*) AS count FROM anime WHERE active=1 GROUP BY scan_status"
                )
            }
            total = int(db.execute("SELECT COUNT(*) FROM anime WHERE active=1").fetchone()[0])
            genre_count = len(
                {genre for row in db.execute("SELECT genres_json FROM anime WHERE active=1") for genre in _loads(row[0])}
            )
        return {
            "found": total,
            "genres": genre_count,
            "completed": counts.get("done", 0),
            "pending": counts.get("pending", 0) + counts.get("in_progress", 0),
            "errors": counts.get("error", 0),
            "catalogue_updated_at": self.get_state("catalogue_updated_at"),
            "catalogue_error": self.get_state("catalogue_error"),
            "catalogue_next_retry_at": self.get_state("catalogue_next_retry_at"),
            "releases_updated_at": self.get_state("releases_updated_at"),
            "releases_error": self.get_state("releases_error"),
            "releases_next_retry_at": self.get_state("releases_next_retry_at"),
        }
