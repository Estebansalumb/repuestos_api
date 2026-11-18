"""Consultas de indicadores y reportes. Leen de las VISTAS de PostgreSQL (V006) y siempre parametrizan."""
from __future__ import annotations

from datetime import date

from Seguridad.contratos import EjecutorSQL


class RepositorioReportes:
    def __init__(self, db: EjecutorSQL):
        self._db = db

    # ------------------------------------------------------------- panel
    def indicadores(self) -> dict:
        return self._db.fetch_one(
            """SELECT (SELECT COUNT(*) FROM v_venta_resumen WHERE state <> 'Cancelada')::int AS sales_count,
                      (SELECT COALESCE(SUM(total), 0) FROM v_venta_resumen WHERE state <> 'Cancelada') AS sales_total,
                      (SELECT COUNT(*) FROM electronic_invoice)::int AS invoices_issued,
                      (SELECT COUNT(*) FROM v_inventario_detalle WHERE needs_reorder)::int AS low_stock_items""")

    def por_estado(self) -> list[dict]:
        return self._db.fetch_all("SELECT state, cantidad AS count, total FROM v_ventas_por_estado ORDER BY sale_state_id")

    def por_mes(self, meses: int = 6) -> list[dict]:
        return self._db.fetch_all("""SELECT to_char(mes, 'YYYY-MM') AS month, cantidad AS count, total
                                     FROM (SELECT * FROM v_ventas_por_mes ORDER BY mes DESC LIMIT %s) t ORDER BY mes""", (meses,))

    def mas_vendidos(self, limite: int = 5, desde: date | None = None, hasta: date | None = None) -> list[dict]:
        if desde is None and hasta is None:
            return self._db.fetch_all("SELECT name, cantidad AS quantity, total FROM v_productos_mas_vendidos "
                                      "ORDER BY cantidad DESC, total DESC LIMIT %s", (limite,))
        return self._db.fetch_all(
            """SELECT p.name, SUM(d.quantity)::int AS quantity, SUM(d.subtotal) AS total
               FROM sale_detail d JOIN v_venta_resumen v ON v.sale_id = d.sale_id JOIN product p ON p.product_id = d.product_id
               WHERE v.state <> 'Cancelada' AND v.sale_date::date BETWEEN %s AND %s
               GROUP BY p.name ORDER BY 2 DESC, 3 DESC LIMIT %s""", (desde, hasta, limite))

    # ------------------------------------------------------------ reportes
    def ventas(self, desde: date, hasta: date, estado: str | None) -> list[dict]:
        params: list = [desde, hasta]
        filtro = ""
        if estado:
            filtro, params = " AND state = %s", [*params, estado]
        return self._db.fetch_all(f"""SELECT sale_id, sale_date, customer_name, state, items, subtotal, tax, total
                                      FROM v_venta_resumen WHERE sale_date::date BETWEEN %s AND %s{filtro}
                                      ORDER BY sale_date""", params)

    def inventario(self, bodega: int | None, solo_bajo: bool) -> list[dict]:
        condiciones, params = [], []
        if bodega:
            condiciones.append("company_warehouse_id = %s")
            params.append(bodega)
        if solo_bajo:
            condiciones.append("needs_reorder")
        donde = " WHERE " + " AND ".join(condiciones) if condiciones else ""
        return self._db.fetch_all(f"""SELECT product_name, category, warehouse_name, quantity_available, reorder_stock,
                                             maximum_stock, needs_reorder FROM v_inventario_detalle{donde}
                                      ORDER BY needs_reorder DESC, quantity_available, product_name""", params)

    def entregas(self, estado: str | None) -> list[dict]:
        params, filtro = [], ""
        if estado:
            filtro, params = " WHERE status = %s", [estado]
        return self._db.fetch_all(f"""SELECT delivery_id, sale_id, customer_name, address, status, tracking_number,
                                             COALESCE(courier, 'Sin asignar') AS courier, delivery_date
                                      FROM v_entrega_detalle{filtro} ORDER BY courier NULLS FIRST, delivery_id""", params)

    def bodegas(self) -> list[tuple[str, str]]:
        return [(str(f["company_warehouse_id"]), f["name"]) for f in
                self._db.fetch_all("SELECT company_warehouse_id, name FROM company_warehouse WHERE state ORDER BY 1")]
