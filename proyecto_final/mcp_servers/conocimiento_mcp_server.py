"""
conocimiento_mcp_server.py
Servidor MCP para recuperación semántica (RAG) sobre la base vectorial de ChromaDB.
Expone la herramienta para consultar políticas, manual de sostenibilidad y FAQs.
"""

import json
from pathlib import Path
from typing import List, Dict, Any

_chroma_store = None


def get_chroma_store():
    global _chroma_store
    if _chroma_store is not None:
        return _chroma_store

    base = Path(__file__).resolve().parent.parent
    candidatos = [
        base / "chroma_db",
        base.parent / "fase3" / "chroma_db",
        Path.cwd() / "chroma_db",
        Path.cwd() / "fase3" / "chroma_db",
        Path("/content/chroma_db"),
        Path("/content/fase3/chroma_db"),
    ]
    chroma_dir = None
    for c in candidatos:
        if c.is_dir():
            chroma_dir = c
            break

    if not chroma_dir:
        return None

    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma

        embed_model = HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True}
        )
        _chroma_store = Chroma(
            collection_name="ecomarket_kb",
            embedding_function=embed_model,
            persist_directory=str(chroma_dir)
        )
        return _chroma_store
    except Exception as e:
        print(f"Aviso al inicializar ChromaDB: {e}")
        return None


def buscar_conocimiento(consulta: str) -> List[Dict[str, Any]]:
    """
    Consulta semánticamente la base de conocimiento vectorial de EcoMarket sobre políticas y normas.
    
    Args:
        consulta: Frase o pregunta en lenguaje natural sobre políticas, devoluciones, envíos o manuales.
    """
    store = get_chroma_store()
    if not store:
        return [{
            "texto": "La base vectorial no está disponible o aún no ha sido indexada.",
            "fuente": "sistema",
            "referencia": "Aviso"
        }]

    try:
        docs = store.similarity_search(consulta, k=4)
        return [
            {
                "texto": d.page_content,
                "fuente": d.metadata.get("fuente", "desconocida"),
                "referencia": d.metadata.get("referencia", "sección"),
            }
            for d in docs
        ]
    except Exception as e:
        return [{"error": f"Fallo en la búsqueda semántica: {str(e)}"}]


# Integración FastMCP
try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("EcoMarket-Conocimiento")

    @mcp.tool()
    def mcp_buscar_conocimiento(consulta: str) -> str:
        """Recupera fragmentos oficiales de políticas, manuales y FAQs mediante búsqueda semántica RAG."""
        return json.dumps(buscar_conocimiento(consulta), ensure_ascii=False)

    HAS_MCP = True
except ImportError:
    mcp = None
    HAS_MCP = False


if __name__ == "__main__":
    import sys
    if HAS_MCP and "--test" not in sys.argv:
        mcp.run()
    else:
        print("=== Test: conocimiento_mcp_server ===")
        print("Búsqueda de prueba:", buscar_conocimiento("daños durante el transporte")[0])

