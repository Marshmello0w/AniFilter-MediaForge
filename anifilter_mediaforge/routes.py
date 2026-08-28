"""AniFilter page and JSON API."""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from . import ENABLED_KEY
from .db import Store
from ..registry import module_admin_required

bp = Blueprint(
    "anifilter_mediaforge",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/thirdparties/anifilter_mediaforge/static",
)


def _enabled():
    from ...db import get_setting

    return get_setting(ENABLED_KEY, "0") == "1"


def _csv(name):
    values = request.args.getlist(name)
    if len(values) == 1:
        values = values[0].split(",")
    return [value.strip() for value in values if value.strip()]


def _with_proxied_poster(item):
    """Use MediaForge's authenticated, cached image proxy for every cover."""
    item = dict(item)
    poster = item.get("poster_url") or ""
    if poster:
        try:
            from ...routes.image_proxy import _poster_proxy

            item["poster_url"] = _poster_proxy(poster)
        except Exception:
            # The browser helper applies the same proxy as a compatibility
            # fallback on MediaForge variants without _poster_proxy.
            item["poster_url"] = poster
    return item


@bp.route("/anifilter")
def index():
    if not _enabled():
        return redirect(url_for("index"))
    return render_template("anifilter.html")


@bp.route("/api/anifilter/catalogue")
def api_catalogue():
    if not _enabled():
        return jsonify({"error": "disabled", "items": []}), 403
    try:
        from ...age_gate import ceiling
        age_ceiling = ceiling()
    except Exception:
        age_ceiling = None
    payload = Store().catalogue(
        {
            "q": request.args.get("q", ""),
            "include": _csv("include"),
            "exclude": _csv("exclude"),
            "genre_mode": request.args.get("genre_mode", "all"),
            "age_mode": request.args.get("age_mode", "all"),
            "ages": _csv("ages"),
            "age_max": request.args.get("age_max", ""),
            "sort": request.args.get("sort", "title_asc"),
            "page": request.args.get("page", "1"),
            "per_page": request.args.get("per_page", "36"),
        },
        age_ceiling=age_ceiling,
    )
    payload["items"] = [_with_proxied_poster(item) for item in payload["items"]]
    return jsonify(payload)


@bp.route("/api/anifilter/anime/<slug>")
def api_anime(slug):
    if not _enabled():
        return jsonify({"error": "disabled"}), 403
    item = Store().get_anime(slug)
    if not item:
        return jsonify({"error": "not found"}), 404
    try:
        from ...age_gate import permits
        if not permits({"fsk": item.get("age_rating")}):
            return jsonify({"error": "age_limited"}), 403
    except Exception:
        pass
    return jsonify(_with_proxied_poster(item))


@bp.route("/api/anifilter/releases/german")
def api_releases():
    if not _enabled():
        return jsonify({"error": "disabled", "items": []}), 403
    payload = Store().german_releases(limit=min(24, max(1, request.args.get("limit", 6, type=int))))
    try:
        from ...age_gate import filter_items
        payload["items"] = filter_items([
            {**item, "fsk": item.get("age_rating")} for item in payload["items"]
        ])
    except Exception:
        pass
    payload["items"] = [_with_proxied_poster(item) for item in payload["items"]]
    return jsonify(payload)


@bp.route("/api/anifilter/status")
def api_status():
    if not _enabled():
        return jsonify({"error": "disabled"}), 403
    return jsonify(Store().status())


@bp.route("/api/anifilter/refresh", methods=["POST"])
@module_admin_required
def api_refresh():
    if not _enabled():
        return jsonify({"error": "disabled"}), 403
    from .scanner import request_refresh
    data = request.get_json(silent=True) or {}
    if not request_refresh(force_details=bool(data.get("details"))):
        return jsonify({"error": "worker is not running"}), 409
    return jsonify({"ok": True}), 202
