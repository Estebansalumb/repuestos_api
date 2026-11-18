"""Servicio de productos e inventario: validación, reglas y auditoría."""
from __future__ import annotations

from psycopg import errors as pgerr

from Seguridad.repositorio import RepositorioAuditoria

from ..core.database import Database
from ..models.errores import ErrorDeNegocio, ErrorValidacion, NoEncontrado
from ..models.negocio import dinero
from ..repositories.productos import RepositorioInventario, RepositorioProductos


def _entero(valor, nombre: str, minimo: int = 0) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ErrorValidacion(f"{nombre} debe ser un número entero")
    if n < minimo:
        raise ErrorValidacion(f"{nombre} no puede ser menor que {minimo}")
    return n


def _opcional_entero(valor, nombre: str) -> int | None:
    return None if valor in (None, "") else _entero(valor, nombre, 1)


class ServicioProductos:
    def __init__(self, db: Database, auditoria: RepositorioAuditoria):
        self._db, self._auditoria = db, auditoria
        self.productos, self.inventario = RepositorioProductos(db), RepositorioInventario(db)

    # ------------------------------------------------------------ productos
    def buscar(self, q=None, car_id=None, car_brand_id=None, type_id=None) -> list[dict]:
        return self.productos.buscar((q or "").strip()[:100] or None, _opcional_entero(car_id, "car_id"),
                                     _opcional_entero(car_brand_id, "car_brand_id"), _opcional_entero(type_id, "type_id"))

    def obtener(self, product_id: int) -> dict:
        return self.productos.obtener(product_id) or self._no_existe()

    def para_vehiculo(self, car_id: int) -> list[dict]:
        if not self.productos.existe_vehiculo(car_id):
            raise NoEncontrado("Vehículo no encontrado")
        return self.productos.buscar(car_id=car_id)

    def _validar(self, d: dict, parcial: bool) -> dict:
        limpio = {}
        if "name" in d or not parcial:
            nombre = str(d.get("name") or "").strip()
            if not nombre or len(nombre) > 150:
                raise ErrorValidacion("El nombre es obligatorio (máximo 150 caracteres)")
            limpio["name"] = nombre
        if "description" in d:
            limpio["description"] = (str(d["description"] or "").strip() or None)
            if limpio["description"] and len(limpio["description"]) > 255:
                raise ErrorValidacion("La descripción admite máximo 255 caracteres")
        if "unit_price" in d or not parcial:
            precio = dinero(d.get("unit_price"))
            if precio < 0:
                raise ErrorValidacion("El precio no puede ser negativo")
            limpio["unit_price"] = precio
        if "fk_car_product" in d:
            vehiculos = d["fk_car_product"] or []
            if not isinstance(vehiculos, list):
                raise ErrorValidacion("fk_car_product debe ser una lista de car_id")
            limpio["fk_car_product"] = sorted({_entero(v, "car_id", 1) for v in vehiculos})
        if "fk_spare_part" in d:
            limpio["fk_spare_part"] = _opcional_entero(d["fk_spare_part"], "fk_spare_part")
        if "state" in d:
            limpio["state"] = bool(d["state"])
        return limpio

    def crear(self, d: dict, usuario, ip) -> dict:
        pid = self._proteger(lambda: self.productos.crear(self._validar(d, parcial=False)))
        self._auditoria.registrar(usuario.id, usuario.nombre_usuario, "CREAR", "producto", f"product_id={pid}", ip)
        return self.obtener(pid)

    def actualizar(self, product_id: int, d: dict, usuario, ip) -> dict:
        if not self._proteger(lambda: self.productos.actualizar(product_id, self._validar(d, parcial=True))):
            self._no_existe()
        self._auditoria.registrar(usuario.id, usuario.nombre_usuario, "ACTUALIZAR", "producto", f"product_id={product_id}", ip)
        return self.obtener(product_id)

    def desactivar(self, product_id: int, usuario, ip) -> None:
        if not self.productos.actualizar(product_id, {"state": False}):
            self._no_existe()
        self._auditoria.registrar(usuario.id, usuario.nombre_usuario, "ELIMINAR", "producto", f"product_id={product_id}", ip)

    # ------------------------------------------------------------ inventario
    def listar_inventario(self, bodega=None, solo_bajo: bool = False) -> list[dict]:
        return self.inventario.listar(_opcional_entero(bodega, "warehouse_id"), solo_bajo)

    def crear_inventario(self, d: dict, usuario, ip) -> dict:
        datos = {"product_id": _entero(d.get("product_id"), "product_id", 1),
                 "company_warehouse_id": _entero(d.get("company_warehouse_id"), "company_warehouse_id", 1),
                 "quantity_available": _entero(d.get("quantity_available"), "quantity_available")}
        for k in ("minimum_stock", "maximum_stock", "reorder_stock"):
            if k in d:
                datos[k] = _entero(d[k], k)
        if self.inventario.existencia(datos["product_id"], datos["company_warehouse_id"]):
            raise ErrorDeNegocio("Ya existe inventario para ese producto y bodega; usa PUT para modificarlo")
        iid = self._proteger(lambda: self.inventario.crear(datos))
        self._auditoria.registrar(usuario.id, usuario.nombre_usuario, "CREAR", "inventario", f"inventory_id={iid}", ip)
        return self.inventario.obtener(iid)

    def actualizar_inventario(self, inventory_id: int, d: dict, usuario, ip) -> dict:
        datos = {k: _entero(d[k], k) for k in ("quantity_available", "minimum_stock", "maximum_stock", "reorder_stock") if k in d}
        if not datos:
            raise ErrorValidacion("No hay campos para actualizar")
        if not self.inventario.actualizar(inventory_id, datos):
            raise NoEncontrado("Registro de inventario no encontrado")
        self._auditoria.registrar(usuario.id, usuario.nombre_usuario, "ACTUALIZAR", "inventario",
                                  f"inventory_id={inventory_id} {datos}", ip)
        return self.inventario.obtener(inventory_id)

    # ------------------------------------------------------------ internos
    @staticmethod
    def _no_existe():
        raise NoEncontrado("Producto no encontrado")

    @staticmethod
    def _proteger(accion):
        try:
            return accion()
        except pgerr.ForeignKeyViolation:
            raise ErrorDeNegocio("Alguna referencia (vehículo, repuesto, bodega o producto) no existe")
        except (pgerr.CheckViolation, pgerr.NumericValueOutOfRange):
            raise ErrorValidacion("Algún valor está fuera del rango permitido")
        except pgerr.UniqueViolation:
            raise ErrorDeNegocio("Ya existe un registro con esos datos")
