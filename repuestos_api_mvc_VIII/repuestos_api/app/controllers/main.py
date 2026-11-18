from __future__ import annotations

from flask import Blueprint, jsonify, render_template

bp = Blueprint("main", __name__)


@bp.get("/")
def inicio():
    """VISTA: la SPA (tienda y panel) se sirve desde una plantilla; los datos llegan por la API JSON."""
    return render_template("index.html")


@bp.get("/api/salud")
def salud():
    return jsonify(estado="ok")
