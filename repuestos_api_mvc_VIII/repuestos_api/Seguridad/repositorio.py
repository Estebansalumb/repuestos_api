"""Acceso a datos de seguridad (SQL parametrizado, sin concatenar valores)."""
from __future__ import annotations

from datetime import datetime

from .contratos import EjecutorSQL
from .modelos import Rol, Usuario

_BASE = """SELECT u.user_id, u.username, u.email, u.password_hash, u.status, u.person_id, u.role,
                  u.bloqueado_hasta, u.intentos_fallidos, u.creado_en, u.ultimo_acceso
           FROM app_user u"""


class RepositorioUsuarios:
    def __init__(self, db: EjecutorSQL):
        self._db = db

    def buscar_por_nombre(self, nombre: str) -> Usuario | None:
        f = self._db.fetch_one(_BASE + " WHERE u.username = %s", (nombre,))
        return Usuario.desde_fila(f) if f else None

    def buscar_por_id(self, id_usuario: int) -> Usuario | None:
        f = self._db.fetch_one(_BASE + " WHERE u.user_id = %s", (id_usuario,))
        return Usuario.desde_fila(f) if f else None

    def existe_nombre_o_email(self, nombre: str, email: str) -> bool:
        return self._db.fetch_one("SELECT 1 AS x FROM app_user WHERE username = %s OR lower(email) = lower(%s)",
                                  (nombre, email)) is not None

    def buscar_con_sesion(self, id_usuario: int, jti: str) -> tuple[Usuario | None, dict | None]:
        """Usuario + su sesión JWT (una sola consulta por petición). None si el token no tiene sesión registrada."""
        f = self._db.fetch_one(
            _BASE.replace("SELECT u.user_id", "SELECT s.agente_hash, s.revocado_en, s.expira_en AS sesion_expira, u.user_id")
            + " JOIN sesion_jwt s ON s.user_id = u.user_id AND s.jti = %s WHERE u.user_id = %s", (jti, id_usuario))
        return (Usuario.desde_fila(f), f) if f else (None, None)

    def listar(self, rol: str | None = None) -> list[dict]:
        sql = """SELECT u.user_id, u.username, u.email, u.status, u.role, u.creado_en, u.ultimo_acceso, u.person_id,
                        p.first_name || ' ' || p.last_name AS nombre_completo,
                        (SELECT COUNT(*) FROM sesion_jwt s WHERE s.user_id = u.user_id AND s.revocado_en IS NULL
                           AND s.expira_en > now())::int AS sesiones_activas
                 FROM app_user u JOIN person p ON p.person_id = u.person_id"""
        if rol:
            return self._db.fetch_all(sql + " WHERE u.role = %s ORDER BY u.username", (rol,))
        return self._db.fetch_all(sql + " ORDER BY u.username")

    def crear(self, nombre: str, email: str, hash_: str, rol: Rol, id_persona: int) -> int:
        f = self._db.fetch_one("INSERT INTO app_user (username, email, password_hash, role, person_id) "
                               "VALUES (%s, %s, %s, %s, %s) RETURNING user_id", (nombre, email, hash_, rol.value, id_persona))
        return f["user_id"]

    def actualizar(self, id_usuario: int, rol: Rol, activo: bool) -> None:
        self._db.execute("UPDATE app_user SET role = %s, status = %s WHERE user_id = %s", (rol.value, activo, id_usuario))

    def cambiar_password(self, id_usuario: int, hash_: str) -> None:
        self._db.execute("UPDATE app_user SET password_hash=%s, intentos_fallidos=0, bloqueado_hasta=NULL WHERE user_id=%s",
                         (hash_, id_usuario))

    def registrar_fallo(self, id_usuario: int, max_intentos: int, bloqueo_min: int) -> None:
        self._db.execute(
            """UPDATE app_user SET
                 intentos_fallidos = CASE WHEN intentos_fallidos + 1 >= %(m)s THEN 0 ELSE intentos_fallidos + 1 END,
                 bloqueado_hasta   = CASE WHEN intentos_fallidos + 1 >= %(m)s THEN now() + make_interval(mins => %(b)s)
                                          ELSE bloqueado_hasta END
               WHERE user_id = %(i)s""", {"m": max_intentos, "b": bloqueo_min, "i": id_usuario})

    def registrar_acceso(self, id_usuario: int) -> None:
        self._db.execute("UPDATE app_user SET intentos_fallidos=0, bloqueado_hasta=NULL, ultimo_acceso=now() WHERE user_id=%s",
                         (id_usuario,))

    # ------------------------------------------------------------ sesiones JWT
    def crear_sesion(self, jti: str, id_usuario: int, expira_en: datetime, ip: str | None, agente_hash: str) -> None:
        self._db.execute("INSERT INTO sesion_jwt (jti, user_id, expira_en, ip, agente_hash) VALUES (%s,%s,%s,%s,%s)",
                         (jti, id_usuario, expira_en, ip, agente_hash))

    def revocar_sesion(self, jti: str, id_usuario: int, motivo: str) -> bool:
        """Revoca UNA sesión activa del usuario. False si no existe, no es suya o ya estaba revocada/vencida."""
        return self._db.execute(
            "UPDATE sesion_jwt SET revocado_en = now(), motivo_revocacion = %s "
            "WHERE jti = %s AND user_id = %s AND revocado_en IS NULL AND expira_en > now()", (motivo, jti, id_usuario)) == 1

    def revocar_sesiones_usuario(self, id_usuario: int, motivo: str, excepto_jti: str | None = None) -> int:
        return self._db.execute(
            "UPDATE sesion_jwt SET revocado_en = now(), motivo_revocacion = %s "
            "WHERE user_id = %s AND revocado_en IS NULL AND expira_en > now() AND jti <> COALESCE(%s, '')",
            (motivo, id_usuario, excepto_jti))

    def sesiones_activas(self, id_usuario: int) -> list[dict]:
        return self._db.fetch_all("SELECT jti, emitido_en, expira_en, ip FROM sesion_jwt WHERE user_id = %s "
                                  "AND revocado_en IS NULL AND expira_en > now() ORDER BY emitido_en DESC", (id_usuario,))


class RepositorioAuditoria:
    def __init__(self, db: EjecutorSQL):
        self._db = db

    def registrar(self, id_usuario: int | None, nombre: str | None, accion: str,
                  entidad: str | None = None, detalle: str | None = None, ip: str | None = None) -> None:
        self._db.execute("INSERT INTO auditoria (user_id, username, accion, entidad, detalle, ip) VALUES (%s,%s,%s,%s,%s,%s)",
                         (id_usuario, (nombre or "")[:40] or None, accion, entidad, (detalle or "")[:500] or None, ip))

    def listar(self, accion: str = "", usuario: str = "", limite: int = 50, desplazamiento: int = 0) -> tuple[list[dict], int]:
        filtros, params = ["TRUE"], []
        if accion:
            filtros.append("accion = %s"); params.append(accion)
        if usuario:
            filtros.append("username ILIKE %s"); params.append(f"%{usuario}%")
        donde = " AND ".join(filtros)
        total = self._db.fetch_one(f"SELECT COUNT(*) AS n FROM auditoria WHERE {donde}", params)["n"]
        filas = self._db.fetch_all(f"SELECT * FROM auditoria WHERE {donde} ORDER BY fecha DESC, id_auditoria DESC LIMIT %s OFFSET %s",
                                   [*params, limite, desplazamiento])
        return filas, total

    def acciones(self) -> list[str]:
        return [f["accion"] for f in self._db.fetch_all("SELECT DISTINCT accion FROM auditoria ORDER BY 1")]
