"""Consultas de productos e inventario. Leen de las vistas v_producto_detalle y v_inventario_detalle (V006)."""
from __future__ import annotations

from Seguridad.contratos import EjecutorSQL

_EDITABLES = ("name", "description", "unit_price", "state", "fk_car_product", "fk_spare_part")


class RepositorioProductos:
    def __init__(self, db: EjecutorSQL):
        self._db = db

    def buscar(self, q: str | None = None, car_id: int | None = None, car_brand_id: int | None = None,
               type_id: int | None = None, solo_activos: bool = True) -> list[dict]:
        condiciones, params = [], []
        if solo_activos:
            condiciones.append("v.state")
        if q:
            condiciones.append("(v.name ILIKE %s OR v.description ILIKE %s OR v.category ILIKE %s)")
            params += [f"%{q}%"] * 3
        if car_id:
            condiciones.append("%s = ANY(v.fk_car_product)")
            params.append(car_id)
        if car_brand_id:
            condiciones.append("v.fk_car_product && ARRAY(SELECT c.car_id FROM car c WHERE c.car_brand_id = %s)")
            params.append(car_brand_id)
        if type_id:
            condiciones.append("v.category_id = %s")
            params.append(type_id)
        donde = " WHERE " + " AND ".join(condiciones) if condiciones else ""
        return self._db.fetch_all(f"SELECT * FROM v_producto_detalle v{donde} ORDER BY v.name, v.product_id", params)

    def obtener(self, product_id: int) -> dict | None:
        return self._db.fetch_one("SELECT * FROM v_producto_detalle WHERE product_id = %s", (product_id,))

    def obtener_varios(self, ids: list[int]) -> dict[int, dict]:
        filas = self._db.fetch_all("SELECT * FROM v_producto_detalle WHERE product_id = ANY(%s)", (list(ids),))
        return {f["product_id"]: f for f in filas}

    def crear(self, datos: dict) -> int:
        return self._db.fetch_one(
            "INSERT INTO product (name, description, unit_price, fk_car_product, fk_spare_part) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING product_id",
            (datos["name"], datos.get("description"), datos["unit_price"], datos.get("fk_car_product") or [],
             datos.get("fk_spare_part")))["product_id"]

    def actualizar(self, product_id: int, datos: dict) -> bool:
        campos = {k: v for k, v in datos.items() if k in _EDITABLES}
        if not campos:
            return self.obtener(product_id) is not None
        asignaciones = ", ".join(f"{k} = %s" for k in campos)          # columnas de una lista blanca fija
        return self._db.execute(f"UPDATE product SET {asignaciones} WHERE product_id = %s", [*campos.values(), product_id]) == 1

    def existe_vehiculo(self, car_id: int) -> bool:
        return self._db.fetch_one("SELECT 1 AS x FROM car WHERE car_id = %s", (car_id,)) is not None


class RepositorioInventario:
    def __init__(self, db: EjecutorSQL):
        self._db = db

    def listar(self, bodega: int | None = None, solo_bajo: bool = False) -> list[dict]:
        condiciones, params = [], []
        if bodega:
            condiciones.append("company_warehouse_id = %s")
            params.append(bodega)
        if solo_bajo:
            condiciones.append("needs_reorder")
        donde = " WHERE " + " AND ".join(condiciones) if condiciones else ""
        return self._db.fetch_all(f"SELECT * FROM v_inventario_detalle{donde} ORDER BY product_name, inventory_id", params)

    def obtener(self, inventory_id: int) -> dict | None:
        return self._db.fetch_one("SELECT * FROM v_inventario_detalle WHERE inventory_id = %s", (inventory_id,))

    def existencia(self, product_id: int, bodega: int, bloquear: bool = False) -> dict | None:
        """Fila de inventario; con ``bloquear`` usa SELECT … FOR UPDATE (evita vender dos veces la misma unidad)."""
        return self._db.fetch_one("SELECT * FROM inventory WHERE product_id = %s AND company_warehouse_id = %s"
                                  + (" FOR UPDATE" if bloquear else ""), (product_id, bodega))

    def crear(self, datos: dict) -> int:
        return self._db.fetch_one(
            "INSERT INTO inventory (product_id, company_warehouse_id, quantity_available, minimum_stock, maximum_stock, reorder_stock) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING inventory_id",
            (datos["product_id"], datos["company_warehouse_id"], datos["quantity_available"], datos.get("minimum_stock", 0),
             datos.get("maximum_stock", 0), datos.get("reorder_stock", 0)))["inventory_id"]

    def actualizar(self, inventory_id: int, datos: dict) -> bool:
        campos = {k: v for k, v in datos.items()
                  if k in ("quantity_available", "minimum_stock", "maximum_stock", "reorder_stock")}
        asignaciones = ", ".join(f"{k} = %s" for k in campos)
        return self._db.execute(f"UPDATE inventory SET {asignaciones} WHERE inventory_id = %s", [*campos.values(), inventory_id]) == 1

    def mover(self, inventory_id: int, delta: int) -> None:
        self._db.execute("UPDATE inventory SET quantity_available = quantity_available + %s WHERE inventory_id = %s",
                         (delta, inventory_id))

    def contar_bajo(self) -> int:
        return self._db.fetch_one("SELECT COUNT(*) AS n FROM v_inventario_detalle WHERE needs_reorder")["n"]
