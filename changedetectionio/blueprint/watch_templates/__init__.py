"""
Watch Templates blueprint — one-click starting points for new watches.

Routes:
    GET  /templates               Browse recipe library (HTML).
    POST /templates/apply         Create a watch from a recipe + URL.
    GET  /templates/api/list      JSON list of all recipes (used by add-watch autodetect).
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from loguru import logger

from .recipes import RECIPES, get_recipe, recipes_by_category


def construct_blueprint(datastore, update_q, queuedWatchMetaData):
    blueprint = Blueprint("watch_templates", __name__, template_folder="templates")

    @blueprint.route("/", methods=["GET"])
    @login_required
    def browse():
        return render_template(
            "browse.html",
            categories=recipes_by_category(),
        )

    @blueprint.route("/apply", methods=["POST"])
    @login_required
    def apply_recipe():
        recipe_id = (request.form.get("recipe_id") or "").strip()
        url = (request.form.get("url") or "").strip()
        tags = (request.form.get("tags") or "").strip()

        if not url:
            flash("Please paste a URL for the new watch.", "error")
            return redirect(url_for("watch_templates.browse"))

        recipe = get_recipe(recipe_id)
        if not recipe:
            flash(f"Unknown template '{recipe_id}'.", "error")
            return redirect(url_for("watch_templates.browse"))

        extras = dict(recipe.get("extras") or {})
        # Prefix the watch title with the recipe name when the recipe didn't set one.
        extras.setdefault("title", recipe["name"])

        try:
            new_uuid = datastore.add_watch(url=url, tag=tags, extras=extras)
        except Exception as e:
            logger.warning(f"watch_templates.apply_recipe failed: {e}")
            flash(f"Could not create watch: {e}", "error")
            return redirect(url_for("watch_templates.browse"))

        if new_uuid and update_q is not None:
            # Queue a first check so the watch gets its initial snapshot promptly.
            try:
                update_q.put(queuedWatchMetaData(priority=1, item={"uuid": new_uuid}))
            except Exception:
                # Queue enqueue is best-effort: the ticker thread will pick it up.
                pass

        flash(
            f"Watch created from template '{recipe['name']}'. "
            f"You can fine-tune filters from the edit screen.",
            "notice",
        )
        return redirect(url_for("watchlist.index"))

    @blueprint.route("/api/list", methods=["GET"])
    @login_required
    def api_list():
        """Minimal JSON list for the add-watch page's autodetect pill."""
        payload = [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "category": r.get("category", "other"),
                "domain_hints": r.get("domain_hints", []),
                "url_example": r.get("url_example", ""),
            }
            for r in RECIPES
        ]
        from flask import jsonify
        return jsonify({"recipes": payload})

    return blueprint
