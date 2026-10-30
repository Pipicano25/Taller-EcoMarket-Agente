"""
devoluciones_mcp_server.py
Servidor MCP para reglas de negocio y gestión de devoluciones (Logística Inversa).
Expone herramientas para verificar la elegibilidad y generar autorizaciones con guías.
"""

import json
import sqlite3
import time
from datetime import datetime, date
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


def verificar_elegibilidad_producto(
    codigo_pedido: str,
    sku_producto: str = "",
    motivo: str = "retracto",
    producto_abierto_o_usado: bool = False
) -> Dict[str, Any]:
    """
    Evalúa si un producto es elegible para devolución según la política de EcoMarket y la Ley 1480.
    
    Args:
        codigo_pedido: Código de la orden (ej. 'ECO-10002').
        sku_producto: SKU del producto a devolver (ej. 'PROD-002'). Opcional (se infiere del pedido).
        motivo: Causa manifestada por el cliente.
        producto_abierto_o_usado: True si se violó el sello primario o fue usado.
    """
    codigo = str(codigo_pedido).strip().upper() if codigo_pedido else ""
    sku = str(sku_producto).strip().upper() if sku_producto else ""
    
    # Manejo defensivo del flag de producto abierto
    if isinstance(producto_abierto_o_usado, str):
        producto_abierto_o_usado = producto_abierto_o_usado.lower() in ["true", "1", "si", "sí", "yes", "abierto", "usado"]
    else:
        producto_abierto_o_usado = bool(producto_abierto_o_usado)

    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM pedidos WHERE codigo_pedido = ?", (codigo,))
    pedido = cur.fetchone()
    if not pedido:
        conn.close()
        return {
            "es_elegible": False,
            "codigo_decision": "PEDIDO_NO_ENCONTRADO",
            "motivo_rechazo": f"No se encontró registro para el pedido {codigo}."
        }

    if pedido["estado_pedido"] != "Entregado":
        conn.close()
        return {
            "es_elegible": False,
            "codigo_decision": "PEDIDO_NO_ENTREGADO",
            "estado_actual": pedido["estado_pedido"],
            "motivo_rechazo": f"Solo procede devolución para pedidos entregados. El pedido {codigo} se encuentra en estado '{pedido['estado_pedido']}'."
        }

    if not sku:
        sku = pedido["sku_producto"]

    if pedido["sku_producto"] != sku:
        conn.close()
        return {
            "es_elegible": False,
            "codigo_decision": "SKU_NO_COINCIDE",
            "motivo_rechazo": f"El producto {sku} no corresponde al artículo del pedido {codigo} ({pedido['producto_nombre']})."
        }

    # Cálculo de días transcurridos respecto a fecha de referencia (05/10/2026)
    dias_transcurridos = 15
    if pedido["fecha_entrega"]:
        try:
            f_ent = datetime.strptime(pedido["fecha_entrega"], "%Y-%m-%d").date()
            dias_transcurridos = max(0, (date(2026, 10, 5) - f_ent).days)
        except Exception:
            pass

    if dias_transcurridos > 30:
        conn.close()
        return {
            "es_elegible": False,
            "codigo_decision": "PLAZO_VENCIDO",
            "dias_transcurridos": dias_transcurridos,
            "motivo_rechazo": f"Han transcurrido {dias_transcurridos} días desde la entrega. El derecho de retracto caduca a los 30 días calendario según la Ley 1480."
        }

    cur.execute("SELECT * FROM inventario WHERE sku = ?", (sku,))
    prod = cur.fetchone()
    conn.close()

    es_sanitario = bool(prod["es_higiene_o_perecedero"]) if prod else False
    if es_sanitario and producto_abierto_o_usado:
        return {
            "es_elegible": False,
            "codigo_decision": "EXCEPCION_SANITARIA_SELLO_ROTO",
            "producto": prod["producto"] if prod else sku,
            "categoria": prod["categoria"] if prod else "Higiene / Cuidado Personal",
            "dias_transcurridos": dias_transcurridos,
            "motivo_rechazo": "Por estrictas razones de salubridad pública y normativa sanitaria (Sección 3 de la Política de Devoluciones), los productos de higiene, cuidado personal o alimentos cuyo empaque o sello de seguridad ha sido abierto o probado NO admiten devolución."
        }

    motivo_lower = motivo.lower()
    if any(p in motivo_lower for p in ["transporte", "dañ", "rot", "golp", "averia"]):
        return {
            "es_elegible": True,
            "codigo_decision": "ELEGIBLE_GARANTIA_TRANSPORTE",
            "requiere_escalamiento_humano": True,
            "dias_transcurridos": dias_transcurridos,
            "mensaje": "Producto con daño reportado durante el transporte. Procede cambio sin costo adjuntando evidencia fotográfica dentro de las primeras 48h para la reclamación con la transportadora.",
            "costo_envio_cliente": 0,
            "plazo_estimado_dias": 3
        }

    return {
        "es_elegible": True,
        "codigo_decision": "ELEGIBLE_RETRACTO_VALIDO",
        "dias_transcurridos": dias_transcurridos,
        "producto": prod["producto"] if prod else sku,
        "mensaje": f"El producto {sku} cumple con todos los requisitos para devolución voluntaria con empaque original intacto.",
        "requiere_costo_envio_cliente": True,
        "plazo_estimado_reembolso_dias": 5
    }


def generar_etiqueta_devolucion(
    codigo_pedido: str,
    sku_producto: str = "",
    nombre_cliente: str = "Cliente EcoMarket",
    ciudad_recogida: str = "Bogotá D.C.",
    tipo_recoleccion: str = "domicilio",
    producto_abierto_o_usado: bool = False
) -> Dict[str, Any]:
    """
    Genera la autorización formal de devolución, registra en la base de datos y emite la guía.
    Valida estrictamente que el pedido exista, esté entregado y no tenga bloqueos normativos.
    
    Args:
        codigo_pedido: Código del pedido.
        sku_producto: SKU del producto a devolver (opcional, se infiere del pedido).
        nombre_cliente: Nombre del remitente.
        ciudad_recogida: Ciudad donde se recogerá el paquete.
        tipo_recoleccion: 'domicilio' o 'sucursal'.
        producto_abierto_o_usado: Indicador si el producto fue abierto o usado.
    """
    codigo = str(codigo_pedido).strip().upper() if codigo_pedido else ""
    sku = str(sku_producto).strip().upper() if sku_producto else ""
    nombre = str(nombre_cliente).strip() if nombre_cliente else "Cliente EcoMarket"
    ciudad = str(ciudad_recogida).strip() if ciudad_recogida else "Bogotá D.C."
    tipo = "domicilio"
    if isinstance(tipo_recoleccion, str):
        tipo = tipo_recoleccion.strip().lower()

    if isinstance(producto_abierto_o_usado, str):
        producto_abierto_o_usado = producto_abierto_o_usado.lower() in ["true", "1", "si", "sí", "yes", "abierto", "usado"]
    else:
        producto_abierto_o_usado = bool(producto_abierto_o_usado)

    # GUARDRAIL INTERNO EN SERVIDOR MCP: Verificar restricciones antes de insertar
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM pedidos WHERE codigo_pedido = ?", (codigo,))
    pedido = cur.fetchone()
    if not pedido:
        conn.close()
        return {"exito": False, "error": f"No se encontró el pedido {codigo}."}

    if pedido["estado_pedido"] != "Entregado":
        conn.close()
        return {"exito": False, "error": f"El pedido {codigo} no está entregado (estado actual: {pedido['estado_pedido']})."}

    if not sku and pedido["sku_producto"]:
        sku = pedido["sku_producto"]

    cur.execute("SELECT es_higiene_o_perecedero, producto FROM inventario WHERE sku = ?", (sku,))
    prod = cur.fetchone()
    if prod and prod["es_higiene_o_perecedero"] and producto_abierto_o_usado:
        conn.close()
        return {
            "exito": False,
            "codigo_decision": "BLOQUEO_SANITARIO",
            "error": f"BLOQUEO DE SEGURIDAD: No se puede generar autorización ni guía para {sku} ({prod['producto']}) porque es un producto de higiene con empaque abierto o usado (Sección 3 y Ley 1480)."
        }

    semilla = abs(hash(f"{codigo}-{sku}-{time.time()}")) % 10000
    radicado = f"RET-2026-{semilla:04d}"
    guia_num = f"GUIA-REV-{semilla:04d}99"
    transportadora = "Coordinadora" if any(c in ciudad.lower() for c in ["medell", "cali"]) else "Servientrega"
    enlace_pdf = f"https://logistica.ecomarket.test/etiquetas/{radicado}.pdf"
    fecha_solicitud = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
    INSERT OR REPLACE INTO devoluciones VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (radicado, codigo, sku, "Devolución aprobada por agente", 0, transportadora, guia_num, enlace_pdf, fecha_solicitud, "Autorizada"))
    conn.commit()
    conn.close()

    modalidad = "Recolección a domicilio por el operador" if tipo == "domicilio" else f"Entrega directa en sucursal {transportadora}"

    return {
        "exito": True,
        "radicado_devolucion": radicado,
        "codigo_pedido": codigo,
        "sku_producto": sku,
        "cliente": nombre,
        "ciudad": ciudad,
        "transportadora": transportadora,
        "numero_guia_retorno": guia_num,
        "modalidad_logistica": modalidad,
        "enlace_descarga_etiqueta": enlace_pdf,
        "fecha_limite_entrega": "5 días hábiles a partir de la fecha de expedición",
        "instrucciones_embalaje": [
            "1. Descarga e imprime la etiqueta PDF adjunta (o presenta el código de barras en el celular).",
            "2. Empaca el artículo en su caja original garantizando que no sufra golpes.",
            "3. Utiliza únicamente material de relleno biodegradable (papel kraft o cartón reciclable).",
            "4. Solicita y conserva la copia firmada de la guía al momento de la entrega al transportador."
        ]
    }


# Integración FastMCP
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("EcoMarket-Devoluciones")

    @mcp.tool()
    def mcp_verificar_elegibilidad_producto(
        codigo_pedido: str,
        sku_producto: str = "",
        motivo: str = "retracto",
        producto_abierto_o_usado: bool = False
    ) -> str:
        """Verifica en SQLite y según la Ley 1480 si un producto es elegible para devolución."""
        return json.dumps(verificar_elegibilidad_producto(
            codigo_pedido, sku_producto, motivo, producto_abierto_o_usado
        ), ensure_ascii=False)

    @mcp.tool()
    def mcp_generar_etiqueta_devolucion(
        codigo_pedido: str,
        sku_producto: str = "",
        nombre_cliente: str = "Cliente EcoMarket",
        ciudad_recogida: str = "Bogotá D.C.",
        tipo_recoleccion: str = "domicilio",
        producto_abierto_o_usado: bool = False
    ) -> str:
        """Genera radicado RET-XXXX, guía de retorno y registra la devolución en SQLite."""
        return json.dumps(generar_etiqueta_devolucion(
            codigo_pedido, sku_producto, nombre_cliente, ciudad_recogida, tipo_recoleccion, producto_abierto_o_usado
        ), ensure_ascii=False)

    HAS_MCP = True
except ImportError:
    mcp = None
    HAS_MCP = False


if __name__ == "__main__":
    import sys
    if HAS_MCP and "--test" not in sys.argv:
        mcp.run()
    else:
        print("=== Test: devoluciones_mcp_server ===")
        print("Elegibilidad PROD-002 (abierto):", verificar_elegibilidad_producto(
            "ECO-10002", "PROD-002", "retracto", producto_abierto_o_usado=True
        ))
        print("\nGenerar Etiqueta ECO-10006:", generar_etiqueta_devolucion(
            "ECO-10006", "PROD-006", "Fredy Alvarez", "Cali", "domicilio"
        ))

