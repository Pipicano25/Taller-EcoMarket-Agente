"""
seed_datos.py
Inicialización y poblado de la base de datos relacional SQLite (ecomarket.db)
a partir de los archivos de contexto corporativo (pedidos.txt e inventario_productos.csv).
"""

import re
import csv
import sqlite3
from pathlib import Path


def buscar_directorio_contexto() -> Path:
    """Localiza la carpeta context con los archivos fuente."""
    base = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    candidatos = [
        base.parent.parent / "context",
        base.parent.parent / "fase3" / "context",
        base.parent / "context",
        Path.cwd() / "context",
        Path.cwd() / "fase3" / "context",
        Path("/content/context"),
        Path("/content/fase3/context"),
        Path("/content/Taller-EcoMarket-Agente/context"),
        Path("/content/Taller-EcoMarket-RAG/fase3/context"),
    ]
    for c in candidatos:
        if c.is_dir() and (c / "inventario_productos.csv").exists() and (c / "pedidos.txt").exists():
            return c

    for found in Path.cwd().glob("**/inventario_productos.csv"):
        if (found.parent / "pedidos.txt").exists():
            return found.parent

    raise FileNotFoundError("No se encontró la carpeta 'context' con inventario y pedidos.")


def formatear_fecha_iso(fecha_str: str) -> str:
    """Convierte fecha DD/MM/YYYY a formato ISO YYYY-MM-DD."""
    if not fecha_str:
        return None
    partes = fecha_str.strip().split("/")
    if len(partes) == 3:
        dia, mes, anio = partes
        return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
    return fecha_str.strip()


def seed_database(db_path: Path = None):
    """Crea las tablas e inserta los datos iniciales."""
    if db_path is None:
        db_path = Path(__file__).resolve().parent.parent / "ecomarket.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    context_dir = buscar_directorio_contexto()

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 1. Tabla Inventario
    cursor.execute("""
    CREATE TABLE inventario (
        sku TEXT PRIMARY KEY,
        producto TEXT NOT NULL,
        categoria TEXT NOT NULL,
        precio_cop INTEGER NOT NULL,
        stock_disponible INTEGER NOT NULL,
        estado_inventario TEXT NOT NULL,
        es_higiene_o_perecedero INTEGER NOT NULL,
        materiales_certificaciones TEXT,
        descripcion_y_uso TEXT
    );
    """)

    # 2. Tabla Pedidos
    cursor.execute("""
    CREATE TABLE pedidos (
        codigo_pedido TEXT PRIMARY KEY,
        producto_nombre TEXT NOT NULL,
        sku_producto TEXT NOT NULL,
        estado_pedido TEXT NOT NULL,
        fecha_entrega TEXT,
        fecha_estimada_entrega TEXT,
        motivo_retraso TEXT,
        transportadora TEXT,
        tracking_url TEXT,
        FOREIGN KEY (sku_producto) REFERENCES inventario(sku)
    );
    """)

    # 3. Tabla Devoluciones (transaccional)
    cursor.execute("""
    CREATE TABLE devoluciones (
        radicado TEXT PRIMARY KEY,
        codigo_pedido TEXT NOT NULL,
        sku_producto TEXT NOT NULL,
        motivo TEXT NOT NULL,
        producto_abierto_o_usado INTEGER NOT NULL,
        transportadora_retorno TEXT NOT NULL,
        guia_retorno TEXT NOT NULL,
        enlace_etiqueta TEXT NOT NULL,
        fecha_solicitud TEXT NOT NULL,
        estado_devolucion TEXT NOT NULL,
        FOREIGN KEY (codigo_pedido) REFERENCES pedidos(codigo_pedido),
        FOREIGN KEY (sku_producto) REFERENCES inventario(sku)
    );
    """)

    # Ingesta Inventario
    csv_file = context_dir / "inventario_productos.csv"
    categorias_sanitarias = ["higiene personal", "cuidado personal e higiene", "alimentos perecederos"]
    sku_map = {}

    with open(csv_file, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row["sku"].strip()
            prod_name = row["producto"].strip()
            cat = row["categoria"].strip()
            precio = int(row["precio_cop"].strip())
            stock = int(row["stock_disponible"].strip())
            estado = row["estado_inventario"].strip()
            mat = row["materiales_certificaciones"].strip()
            desc = row["descripcion_y_uso"].strip()

            es_sanitario = 1 if any(c in cat.lower() for c in categorias_sanitarias) else 0

            cursor.execute("""
            INSERT INTO inventario VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, prod_name, cat, precio, stock, estado, es_sanitario, mat, desc))
            sku_map[prod_name.lower()] = sku

    # Ingesta Pedidos
    txt_file = context_dir / "pedidos.txt"
    contenido = txt_file.read_text(encoding="utf-8")
    bloques = [b.strip() for b in re.split(r"(?m)^PEDIDO\s+\d+", contenido) if b.strip()]

    for bloque in bloques:
        m_cod = re.search(r"Número de seguimiento:\s*(ECO-\d+)", bloque)
        m_prod = re.search(r"Producto:\s*([^\n]+)", bloque)
        m_est = re.search(r"Estado:\s*([^\n]+)", bloque)
        m_f_ent = re.search(r"Fecha de entrega:\s*([^\n]+)", bloque)
        m_f_est = re.search(r"Fecha estimada de entrega:\s*([^\n]+)", bloque)
        m_mot = re.search(r"Motivo:\s*([^\n]+)", bloque)
        m_trans = re.search(r"Transportadora:\s*([^\n]+)", bloque)
        m_track = re.search(r"Enlace de seguimiento:\s*([^\n]+)", bloque)

        if m_cod and m_prod and m_est:
            c = m_cod.group(1).strip()
            prod_nom = m_prod.group(1).strip()
            est = m_est.group(1).strip()
            fe = formatear_fecha_iso(m_f_ent.group(1)) if m_f_ent else None
            fe_est = formatear_fecha_iso(m_f_est.group(1)) if m_f_est else None
            mot = m_mot.group(1).strip() if m_mot else None
            tr = m_trans.group(1).strip() if m_trans else None
            tk = m_track.group(1).strip() if m_track else None

            sku = sku_map.get(prod_nom.lower(), "PROD-001")

            cursor.execute("""
            INSERT INTO pedidos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (c, prod_nom, sku, est, fe, fe_est, mot, tr, tk))

    conn.commit()
    conn.close()
    print(f"[seed_datos] Base de datos SQLite creada exitosamente en: {db_path}")


if __name__ == "__main__":
    seed_database()
