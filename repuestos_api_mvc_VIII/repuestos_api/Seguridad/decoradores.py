from __future__ import annotations

from functools import wraps

from flask import g, jsonify, redirect, request

from .modelos import Rol, Usuario


def usuario_actual() -> Usuario | None:
    return getattr(g, "usuario", None)


def _es_api() -> bool:
    return request.path.startswith("/api/")


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if usuario_actual() is None:
            if _es_api():
                return jsonify(error="Debes iniciar sesión"), 401
            return redirect("/#/login")
        return vista(*args, **kwargs)
    return envoltura


def rol_requerido(*roles: Rol):
    permitidos = {r.value if isinstance(r, Rol) else r for r in roles}

    def decorador(vista):
        @wraps(vista)
        @login_requerido
        def envoltura(*args, **kwargs):
            if usuario_actual().rol.value not in permitidos:
                return jsonify(error="Tu rol no permite realizar esta acción"), 403
            return vista(*args, **kwargs)
        return envoltura
    return decorador
