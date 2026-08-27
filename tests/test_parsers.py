import unittest

from anifilter_mediaforge.parsers import merge_catalogues, parse_catalogue, parse_german_releases


def release_row(slug, stamp, flag="german", episode=1):
    return f"""<div class="col-md-12"><img class="flag" src="/public/img/{flag}.svg">
    <a href="/anime/stream/{slug}/staffel-1/episode-{episode}"><strong>{slug}</strong>
    <span class="elementFloatRight">{stamp}</span></a></div>"""


class ParserTests(unittest.TestCase):
    def test_catalogue_parses_genres_and_alphabet_entries(self):
        genre_html = """
        <div id="seriesContainer">
          <div class="genre"><h3>Harem</h3><ul>
            <li><a href="/anime/stream/show-a" data-alternative-title="Alias A">Show A</a></li>
          </ul></div>
          <div class="genre"><h3>Ger</h3><ul>
            <li><a href="/anime/stream/show-a">Show A</a></li>
          </ul></div>
        </div>"""
        alphabet_html = '<div id="seriesContainer"><li><a href="/anime/stream/show-b">Show B</a></li></div>'
        merged = merge_catalogues(parse_catalogue(genre_html), parse_catalogue(alphabet_html))
        self.assertEqual([row["slug"] for row in merged], ["show-a", "show-b"])
        show_a = next(row for row in merged if row["slug"] == "show-a")
        self.assertEqual(show_a["genres"], ["Harem", "Ger"])
        self.assertEqual(show_a["aliases"], ["Alias A"])

    def test_releases_keep_german_audio_and_newest_episode(self):
        filler = "".join(release_row(f"filler-{i}", "Mo, 24.08.2026", "japanese-english") for i in range(20))
        html = '<div class="pageTitle"><h2>22 neuesten Episoden</h2></div><div class="newEpisodeList"><div class="rows">' + filler
        html += release_row("german-show", "Di, 25.08.2026", episode=2)
        html += release_row("german-show", "Mi, 26.08.2026", episode=3) + "</div></div>"
        result = parse_german_releases(html)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slug"], "german-show")
        self.assertEqual(result[0]["episode"], 3)
        self.assertEqual(result[0]["released_on"], "2026-08-26")

    def test_releases_reject_truncated_page(self):
        with self.assertRaisesRegex(ValueError, "too few"):
            parse_german_releases('<h2>150 neuesten Episoden</h2><div class="col-md-12"></div>')


if __name__ == "__main__":
    unittest.main()

