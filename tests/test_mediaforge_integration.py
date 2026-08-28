import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MediaForgeIntegrationAssetTests(unittest.TestCase):
    def test_page_loads_mediaforge_native_series_modal(self):
        template = (ROOT / "anifilter_mediaforge" / "templates" / "anifilter.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('{% include "shared_modals.html" %}', template)
        self.assertIn("filename='app.js'", template)
        self.assertNotIn('id="afModal"', template)

    def test_cards_use_native_open_series_and_do_not_double_proxy_images(self):
        script = (ROOT / "anifilter_mediaforge" / "static" / "anifilter.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.openSeries(seriesUrl)", script)
        self.assertIn('url.startsWith("/api/img?")', script)


if __name__ == "__main__":
    unittest.main()
