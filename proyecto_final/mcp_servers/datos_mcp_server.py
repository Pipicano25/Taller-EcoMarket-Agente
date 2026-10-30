"""
datos_mcp_server.py
Servidor MCP para consulta de datos transaccionales y maestros en SQLite (ecomarket.db).
Expone herramientas para consultar pedidos e inventario de productos.
"""

import re
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any


def get_db_path() -> Path:
    base = Path(__file__).resolve().parent.parent
    candidatos = [
        base / "ecomarket.db",
        Path.cwd() / "proyecto_final" / "ecomarket.db",
        Path.cwd() / "ecomarket.db",
        Path("/content/ecomarket.db"),
        Path("/content/proyecto_final/ecomarket.db"),
    ]
    for c in candidatos:
        if c.is_file():
            return c
    for found in Path.cwd().glob("**/ecomarket.db"):
        return found
    return base / "ecomarket.db"


def consultar_pedido(codigo_pedido: str) -> Dict[str, Any]:
    """
    Consulta los detalles y estado de una orden de compra en la base de datos de EcoMarket.
    
    Args:
        codigo_pedido: Código del pedido (ej. 'ECO-10001', 'ECO-10002').
    """
    codigo = codigo_pedido.strip().upper()
    if not re.fullmatch(r"ECO-\d{5}", codigo):
        return {"error": f"Formato de código inválido ({codigo}). Debe ser ECO-XXXXX."}

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM pedidos WHERE codigo_pedido = ?", (codigo,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"encontrado": False, "mensaje": f"El pedido {codigo} no existe en la base de datos."}

    return {
        "encontrado": True,
        "codigo_pedido": row["codigo_pedido"],
        "producto_nombre": row["producto_nombre"],
        "sku_producto": row["sku_producto"],
        "estado_pedido": row["estado_pedido"],
        "fecha_entrega": row["fecha_entrega"],
        "fecha_estimada_entrega": row["fecha_estimada_entrega"],
        "motivo_retraso": row["motivo_retraso"],
        "transportadora": row["transportadora"],
        "tracking_url": row["tracking_url"]
    }


def consultar_inventario(sku: str) -> Dict[str, Any]:
    """
    Consulta especificaciones técnicas, precio, existencias y si un producto es sanitario en el catálogo.
    
    Args:
        sku: Identificador único del producto (ej. 'PROD-001' a 'PROD-012').
    """
    sku_limpio = sku.strip().upper()
    if not re.fullmatch(r"PROD-\d{3}", sku_limpio):
        return {"error": f"Formato de SKU inválido ({sku_limpio}). Debe ser PROD-XXX."}

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM inventario WHERE sku = ?", (sku_limpio,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"encontrado": False, "mensaje": f"El producto {sku_limpio} no existe en el catálogo."}

    return {
        "encontrado": True,
        "sku": row["sku"],
        "producto": row["producto"],
        "categoria": row["categoria"],
        "precio_cop": row["precio_cop"],
        "stock_disponible": row["stock_disponible"],
        "estado_inventario": row["estado_inventario"],
        "es_higiene_o_perecedero": bool(row["es_higiene_o_perecedero"]),
        "materiales_certificaciones": row["materiales_certificaciones"],
        "descripcion_y_uso": row["descripcion_y_uso"]
    }


# Integración FastMCP
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("EcoMarket-Datos")

    @mcp.tool()
    def mcp_consultar_pedido(codigo_pedido: str) -> str:
        """Consulta los detalles de un pedido en la base de datos de EcoMarket."""
        return json.dumps(consultar_pedido(codigo_pedido), ensure_ascii=False)

    @mcp.tool()
    def mcp_consultar_inventario(sku: str) -> str:
        """Consulta el catálogo maestro de inventario por SKU."""
        return json.dumps(consultar_inventario(sku), ensure_ascii=False)

    HAS_MCP = True
except ImportError:
    mcp = None
    HAS_MCP = False


if __name__ == "__main__":
    import sys
    if HAS_MCP and "--test" not in sys.argv:
        mcp.run()
    else:
        print("=== Test: datos_mcp_server ===")
        print("Pedido ECO-10002:", consultar_pedido("ECO-10002"))
        print("Inventario PROD-002:", consultar_inventario("PROD-002"))

