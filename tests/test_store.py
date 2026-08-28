import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from anifilter_mediaforge.db import Store, normalize_poster_url
from anifilter_mediaforge.scanner import Scanner


def entry(slug, genres=None):
    return {
        "slug": slug,
        "url": f"https://aniworld.to/anime/stream/{slug}",
        "title": slug.replace("-", " ").title(),
        "aliases": [],
        "genres": genres or [],
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def populated(self):
        store = Store(Path(self.temp.name) / "test.sqlite")
        store.initialize()
        rows = [entry(f"filler-{index}") for index in range(100)]
        rows += [entry("green", ["Action", "Ger"]), entry("red", ["Harem", "Ecchi"]), entry("mixed", ["Action", "Harem"])]
        store.upsert_catalogue(rows)
        store.save_detail("green", {"title": "Green", "genres": ["Action", "Ger"], "age_rating": 12, "release_year": "2026"})
        store.save_detail("red", {"title": "Red", "genres": ["Harem", "Ecchi"], "age_rating": 18, "release_year": "2024"})
        store.save_detail("mixed", {"title": "Mixed", "genres": ["Action", "Harem"], "age_rating": 16, "release_year": "2025"})
        return store

    def test_include_exclude_and_any_all(self):
        store = self.populated()
        result = store.catalogue({"include": ["Action"], "exclude": ["Harem"], "genre_mode": "all"})
        titles = {item["slug"] for item in result["items"]}
        self.assertIn("green", titles)
        self.assertNotIn("mixed", titles)
        self.assertNotIn("red", titles)
        result = store.catalogue({"include": ["Ger", "Harem"], "genre_mode": "any", "per_page": 96})
        titles = {item["slug"] for item in result["items"]}
        self.assertTrue({"green", "red", "mixed"}.issubset(titles))

    def test_multiple_exact_ages_and_all_mode(self):
        store = self.populated()
        result = store.catalogue({"age_mode": "exact", "ages": ["12", "18"], "per_page": 96})
        self.assertEqual({item["slug"] for item in result["items"]}, {"green", "red"})
        result = store.catalogue({"age_mode": "all", "ages": ["12"]})
        self.assertEqual(result["total"], 103)

    def test_fsk_18_is_always_available_when_account_allows_it(self):
        path = Path(self.temp.name) / "fsk.sqlite"
        store = Store(path)
        store.initialize()
        store.upsert_catalogue([entry(f"show-{index}") for index in range(100)])
        self.assertEqual(store.catalogue({})["facets"]["ages"], [0, 6, 12, 16, 18])
        self.assertEqual(store.catalogue({}, age_ceiling=16)["facets"]["ages"], [0, 6, 12, 16])

    def test_existing_poster_urls_are_normalized_without_rescan(self):
        self.assertEqual(
            normalize_poster_url("/public/img/cover/show.png"),
            "https://aniworld.to/public/img/cover/show.png",
        )
        self.assertEqual(
            normalize_poster_url("https://aniworld.tohttps://cdn.aniworld.to/show.webp"),
            "https://cdn.aniworld.to/show.webp",
        )
        self.assertEqual(normalize_poster_url("data:image/png;base64,abc"), "")

    def test_release_fill_order_and_ger_attachment(self):
        store = self.populated()
        releases = [("green", "2026-08-27"), ("mixed", "2026-08-10"), ("red", "2025-12-31")]
        store.save_releases([
            {"slug": slug, "released_on": stamp, "season": 1, "episode": index + 1,
             "episode_url": f"https://aniworld.to/anime/stream/{slug}/staffel-1/episode-{index + 1}"}
            for index, (slug, stamp) in enumerate(releases)
        ])
        result = store.german_releases(limit=3, reference=date(2026, 8, 28))
        self.assertEqual([item["group"] for item in result["items"]], ["week", "month", "older"])
        self.assertIn("Ger", store.get_anime("red")["genres"])

    def test_restart_resets_in_progress_without_losing_metadata(self):
        path = Path(self.temp.name) / "resume.sqlite"
        store = Store(path)
        store.initialize()
        store.upsert_catalogue([entry(f"show-{index}") for index in range(100)])
        self.assertIsNotNone(store.next_scan_item())
        reader = Store(path)
        with reader.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM anime WHERE scan_status='in_progress'").fetchone()[0],
                1,
            )
        reader.status()
        with reader.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM anime WHERE scan_status='in_progress'").fetchone()[0],
                1,
            )
        reader.initialize()
        self.assertEqual(reader.status()["pending"], 100)

    def test_refresh_failures_use_persistent_backoff(self):
        path = Path(self.temp.name) / "backoff.sqlite"
        store = Store(path)
        store.initialize()

        class Logger:
            def __getattr__(self, _name):
                return lambda *_args, **_kwargs: None

        class App:
            logger = Logger()

        scanner = Scanner(App())
        scanner.store = store
        self.assertTrue(scanner._refresh_due("catalogue", 24))
        first_retry = store.mark_refresh_error("catalogue", "temporary failure")
        self.assertFalse(scanner._refresh_due("catalogue", 24))
        second_retry = store.mark_refresh_error("catalogue", "temporary failure")
        self.assertGreater(datetime.fromisoformat(second_retry), datetime.fromisoformat(first_retry))
        store.set_state(
            "catalogue_next_retry_at",
            (datetime.now().astimezone() - timedelta(seconds=1)).isoformat(timespec="seconds"),
        )
        self.assertTrue(scanner._refresh_due("catalogue", 24))


if __name__ == "__main__":
    unittest.main()
