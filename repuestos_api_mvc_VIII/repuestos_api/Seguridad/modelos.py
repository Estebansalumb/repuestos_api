from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Rol(str, Enum):
    CLIENTE = "cliente"
    ADMINISTRADOR = "administrador"
    EMPACADOR = "empacador"
    REPARTIDOR = "repartidor"


PERSONAL = (Rol.ADMINISTRADOR, Rol.EMPACADOR, Rol.REPARTIDOR)


@dataclass(frozen=True)
class Usuario:
    id: int
    nombre_usuario: str
    email: str
    rol: Rol
    id_persona: int | None = None
    activo: bool = True
    password_hash: str = ""
    bloqueado_hasta: datetime | None = None

    @property
    def es_admin(self) -> bool:
        return self.rol is Rol.ADMINISTRADOR

    @property
    def es_personal(self) -> bool:
        return self.rol in PERSONAL

    @classmethod
    def desde_fila(cls, f: dict) -> "Usuario":
        return cls(f["user_id"], f["username"], f["email"], Rol(f["role"]), f.get("person_id"),
                   f["status"], f.get("password_hash", ""), f.get("bloqueado_hasta"))
