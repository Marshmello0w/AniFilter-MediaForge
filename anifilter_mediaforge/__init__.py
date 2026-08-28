from __future__ import annotations

MODULE_NAME = "AniFilter"
MODULE_DESCRIPTION = "Advanced AniWorld genre and age filters with German release tracking."
MODULE_DESCRIPTION_DE = "Erweiterte AniWorld-Genre- und Altersfilter mit deutschen Neuerscheinungen."
MODULE_AUTHOR = "Marshmello0w"
MODULE_ENABLED_DEFAULT = False
MODULE_VERSION = "1.0.2"
MODULE_API_VERSION = 1
MODULE_MIN_APP_VERSION = "1.5.0"
MODULE_MAX_APP_VERSION = ""
MODULE_REQUIREMENTS = ()
MODULE_ID = "anifilter_mediaforge"
MODULE_HOMEPAGE = "https://github.com/Marshmello0w/AniFilter-MediaForge"
MODULE_LICENSE = ""

ITEM_ID = MODULE_ID
ENABLED_KEY = f"module:{MODULE_ID}:enabled"
SPEED_KEY = f"module:{MODULE_ID}:scan_speed"
HOME_FEED_KEY = "source_enabled_anifilter_german_releases"

_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 5h16M7 12h10M10 19h4"></path>'
    '<circle cx="18" cy="12" r="2"></circle></svg>'
)


def register(app) -> None:
    from .routes import bp
    from .scanner import start_worker, stop_worker
    from ..registry import register_background_worker, register_thirdparty

    app.register_blueprint(bp)
    register_thirdparty(
        item_id=ITEM_ID,
        label="AniFilter",
        endpoint="anifilter_mediaforge.index",
        icon_svg=_ICON,
        enabled_setting_key=ENABLED_KEY,
        description=(
            "Filter the complete AniWorld catalogue by multiple included or excluded "
            "genres and exact age ratings. Uses AniWorld data only."
        ),
        enable_label="AniFilter aktivieren",
        enable_desc="Fügt AniFilter unter Entdecken hinzu und startet den fortsetzbaren Metadaten-Scan.",
        section="discover",
        settings_host="integrations",
        settings_tab="anifilter_mediaforge",
        settings_tab_label="AniFilter",
        overview_description="Mehrfach-Genre-, Negativ- und FSK-Filter für AniWorld.",
        overview_icon_svg=_ICON,
        extra_settings=[
            {
                "key": SPEED_KEY,
                "label": "Scan-Geschwindigkeit",
                "description": "Normal ist für die meisten Installationen empfohlen; bei Limits wird automatisch pausiert.",
                "type": "select",
                "default": "normal",
                "options": [
                    ("gentle", "Schonend (1 Anfrage/s)"),
                    ("normal", "Normal (bis 2 parallel)"),
                    ("fast", "Schnell (bis 3 parallel)"),
                ],
            },
            {
                "key": HOME_FEED_KEY,
                "label": "Neu auf Deutsch auf der Startseite",
                "description": "Mischt bestätigte deutsche AniWorld-Releases in MediaForges Entdecken-Feed.",
                "type": "toggle",
                "default": "1",
            },
        ],
    )

    register_background_worker(ITEM_ID, start=start_worker, stop=stop_worker)

    try:
        from ....home_feed import register_home_feed_source

        register_home_feed_source(
            ITEM_ID,
            source_id="anifilter_german_releases",
            label="AniFilter · Neu auf Deutsch",
            fetchers={"new": _home_feed_new},
            media_type="series",
        )
    except Exception:
        app.logger.debug("[AniFilter] Discover feed registration unavailable", exc_info=True)

    try:
        from ...routes.image_proxy import register_image_hosts

        register_image_hosts(ITEM_ID, hosts=("aniworld.to",), domains=("aniworld.to",))
    except Exception:
        app.logger.debug("[AniFilter] image host registration unavailable", exc_info=True)


def _home_feed_new():
    from .db import Store

    cards = []
    for item in Store().german_releases(limit=12)["items"]:
        cards.append(
            {
                "title": item["title"],
                "url": item["url"],
                "poster_url": item.get("poster_url") or "",
                "genre": "Ger · " + item["period_label"],
            }
        )
    return cards


def on_install(app) -> None:
    from .db import Store

    Store().initialize()
    app.logger.info("[AniFilter] installed v%s", MODULE_VERSION)


def on_upgrade(app, from_version, to_version) -> None:
    from .db import Store

    Store().initialize()
    app.logger.info("[AniFilter] upgraded %s -> %s", from_version, to_version)
