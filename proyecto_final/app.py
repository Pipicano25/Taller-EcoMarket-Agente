"""
app.py
Aplicación Web de EcoMarket en Streamlit para Atención al Cliente y Automatización de Devoluciones.
Integra LangGraph + MCP Servers (Datos, Devoluciones, Conocimiento RAG) + SQLite + Ollama Cloud.
"""

import os
import re
import json
import sqlite3
import time
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# Configuración de página
st.set_page_config(
    page_title="EcoMarket — Asistente de Devoluciones",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================================
# CONEXIÓN CON LOS SERVIDORES MCP Y BASE DE DATOS
# ============================================================================
from mcp_servers.datos_mcp_server import consultar_pedido, consultar_inventario
from mcp_servers.devoluciones_mcp_server import verificar_elegibilidad_producto, generar_etiqueta_devolucion
from mcp_servers.conocimiento_mcp_server import buscar_conocimiento

HERRAMIENTAS = {
    "buscar_conocimiento": buscar_conocimiento,
    "consultar_pedido": consultar_pedido,
    "consultar_inventario": consultar_inventario,
    "verificar_elegibilidad_producto": verificar_elegibilidad_producto,
    "generar_etiqueta_devolucion": generar_etiqueta_devolucion
}

def get_db_path():
    base = Path(__file__).resolve().parent
    for p in [base / "ecomarket.db", Path.cwd() / "ecomarket.db", Path("/content/ecomarket.db")]:
        if p.is_file(): return p
    return base / "ecomarket.db"


# ============================================================================
# AGENTE LANGGRAPH (ORQUESTADOR)
# ============================================================================
from ollama import Client
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class AgentState(TypedDict, total=False):
    consulta: str
    plan: list[dict]
    evidencia: list[dict]
    respuesta: str

SYSTEM_PROMPT = """Eres EcoBot, asistente proactivo de atención al cliente de EcoMarket.
Cuentas con herramientas MCP para consultar pedidos, catálogo, validar políticas de devolución en SQLite y recuperar información documental en ChromaDB.

REGLAS CRÍTICAS DE CONDUCTA:
1. Responde siempre en español, de forma cálida, empática y profesional.
2. Si un cliente solicita una devolución y FALTAN DATOS indispensables (como el número de pedido ECO-XXXXX o si el producto fue abierto/usado), NO ejecutes herramientas a ciegas: pídele amablemente los datos faltantes.
3. Si un producto es de higiene/cuidado personal y fue ABIERTO o USADO, rechaza amablemente la devolución citando la Sección 3 de la política sanitaria, y ofrece recomendaciones ecológicas de aprovechamiento del manual.
4. Para daños en transporte, aclara que requiere escalamiento a agente humano con fotos dentro de las primeras 48h.
5. Si te piden operaciones fuera de tu alcance (ej. cancelar pagos bancarios directos o transacciones sin devolución), explica con transparencia que no tienes permisos transaccionales directos.
6. Cita siempre al final las FUENTES oficiales utilizadas.
"""

@st.cache_resource
def get_ollama_client(api_key: str):
    return Client(host="https://ollama.com", headers={"Authorization": f"Bearer {api_key}"}, timeout=120)

def invocar_llm(mensajes, api_key: str):
    cliente = get_ollama_client(api_key)
    res = cliente.chat(model="glm-5.3-flash", messages=mensajes, stream=False)
    return (res.message.content or "").strip()

def compilar_agente(api_key: str):
    def leer_json(raw):
        raw = raw.strip()
        bloque = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
        if bloque: raw = bloque.group(1).strip()
        return json.loads(raw)

    def planificador(state: AgentState):
        consulta = state["consulta"]
        prompt = f"""Analiza la consulta del cliente y decide el plan de herramientas MCP:
Herramientas:
- buscar_conocimiento(consulta): Consulta políticas, manuales y FAQs en ChromaDB.
- consultar_pedido(codigo_pedido): Consulta órdenes en SQLite.
- consultar_inventario(sku): Consulta catálogo en SQLite.
- verificar_elegibilidad_producto(codigo_pedido, sku_producto, motivo, producto_abierto_o_usado): Valida reglas de 30 días, empaque y excepciones sanitarias.
- generar_etiqueta_devolucion(codigo_pedido, sku_producto, nombre_cliente, ciudad_recogida): Emite la guía de retorno.

REGLAS CRÍTICAS DE PLANIFICACIÓN:
1. Para trámites de devolución, planifica ÚNICAMENTE 'verificar_elegibilidad_producto'. NO agregues 'generar_etiqueta_devolucion' de forma preventiva; el ejecutor la generará automáticamente SOLO si la elegibilidad resulta aprobada (es_elegible: true).
2. Si un producto es de higiene/cuidado personal y fue abierto o usado, NUNCA debe generarse etiqueta.
3. Si la consulta es puramente informativa, usa 'buscar_conocimiento'.
4. Si faltan datos indispensables o la solicitud está fuera de alcance, responde {{"acciones": []}}.

CONSULTA: {consulta}
Responde ÚNICAMENTE JSON: {{"acciones": [{{"herramienta": "...", "parametros": {{...}}}}]}}"""
        raw = invocar_llm([{"role": "user", "content": prompt}], api_key)
        try:
            acciones = leer_json(raw).get("acciones", [])
        except Exception:
            acciones = []
            if "ECO-" in consulta.upper():
                cod = re.search(r"ECO-\d{5}", consulta.upper()).group(0)
                acciones.append({"herramienta": "consultar_pedido", "parametros": {"codigo_pedido": cod}})
            else:
                acciones.append({"herramienta": "buscar_conocimiento", "parametros": {"consulta": consulta}})
        return {"plan": acciones, "evidencia": []}

    def ejecutor(state: AgentState):
        plan = state.get("plan", [])
        evidencias = []
        es_elegible_global = None

        for paso in plan:
            tool = paso.get("herramienta")
            params = paso.get("parametros", {})

            # GUARDRAIL CRÍTICO DE SEGURIDAD:
            # Si el planificador intentó llamar generar_etiqueta_devolucion pero la elegibilidad fue rechazada, BLOQUEAR
            if tool == "generar_etiqueta_devolucion":
                if es_elegible_global is False:
                    evidencias.append({
                        "herramienta": tool,
                        "resultado": {
                            "exito": False,
                            "bloqueado": True,
                            "motivo": "ACCIÓN BLOQUEADA POR GUARDRAIL: No se emite guía ni autorización porque el producto fue rechazado por reglas normativas (Sección 3 y Ley 1480)."
                        }
                    })
                    continue
                params.setdefault("nombre_cliente", "Cliente EcoMarket")
                params.setdefault("ciudad_recogida", "Bogotá D.C.")
                params.setdefault("sku_producto", "")

            if tool in HERRAMIENTAS:
                try:
                    res = HERRAMIENTAS[tool](**params)
                    evidencias.append({"herramienta": tool, "parametros": params, "resultado": res})

                    if tool == "verificar_elegibilidad_producto":
                        es_elegible_global = res.get("es_elegible", False)
                        # Solo si es elegible y no requiere escalamiento humano, generar automáticamente la guía
                        if es_elegible_global and not res.get("requiere_escalamiento_humano"):
                            if any(w in state["consulta"].lower() for w in ["genera", "etiqueta", "guía", "tramita", "devolver", "devolución"]):
                                if not any(p.get("herramienta") == "generar_etiqueta_devolucion" for p in plan):
                                    cod_ped = params.get("codigo_pedido")
                                    if not cod_ped:
                                        m = re.search(r"ECO-\d{5}", state["consulta"].upper())
                                        cod_ped = m.group(0) if m else "ECO-10006"
                                    sku_p = params.get("sku_producto", "")
                                    etiqueta = generar_etiqueta_devolucion(
                                        codigo_pedido=cod_ped,
                                        sku_producto=sku_p,
                                        nombre_cliente=params.get("nombre_cliente", "Cliente EcoMarket"),
                                        ciudad_recogida=params.get("ciudad_recogida", "Bogotá D.C."),
                                        producto_abierto_o_usado=params.get("producto_abierto_o_usado", False)
                                    )
                                    evidencias.append({"herramienta": "generar_etiqueta_devolucion", "resultado": etiqueta})
                except Exception as e:
                    evidencias.append({"herramienta": tool, "error": str(e)})
        return {"evidencia": evidencias}

    def responder(state: AgentState):
        consulta = state["consulta"]
        evidencias = state.get("evidencia", [])
        ctx = json.dumps(evidencias, ensure_ascii=False, indent=2) if evidencias else "NO SE EJECUTARON HERRAMIENTAS"
        prompt = f"CONSULTA DEL CLIENTE:\n{consulta}\n\nEVIDENCIA MCP:\n{ctx}\n\nRedacta la respuesta final empática y fundamentada:"
        resp = invocar_llm([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}], api_key)
        return {"respuesta": resp}

    workflow = StateGraph(AgentState)
    workflow.add_node("planificador", planificador)
    workflow.add_node("ejecutor", ejecutor)
    workflow.add_node("responder", responder)
    workflow.add_edge(START, "planificador")
    workflow.add_edge("planificador", "ejecutor")
    workflow.add_edge("ejecutor", "responder")
    workflow.add_edge("responder", END)
    return workflow.compile()


# ============================================================================
# BARRA LATERAL (CONFIGURACIÓN, CONTROLES Y AUDITORÍA)
# ============================================================================
with st.sidebar:
    st.image("https://img.icons8.com/color/96/natural-food.png", width=64)
    st.title("EcoBot Control")
    st.caption("Arquitectura Agéntica Multiserver MCP")

    # API Key Input
    api_key_input = st.text_input("Ollama API Key", value=OLLAMA_API_KEY, type="password")
    if api_key_input:
        OLLAMA_API_KEY = api_key_input

    st.divider()

    st.subheader("💡 Consultas de Prueba")
    tab_tf, tab_t2 = st.tabs(["🚀 Taller Final", "📜 Taller 2"])

    with tab_tf:
        st.caption("Casos Rúbrica Taller Final (Agente y Devoluciones):")
        casos_tf = [
            ("📅 1. Plazos y Políticas (RAG)", "¿Cuáles son los plazos y condiciones generales para solicitar una devolución en EcoMarket?"),
            ("📦 2. Consulta Inventario (SQL)", "¿Qué precio tiene y qué certificaciones ambientales posee el producto PROD-003?"),
            ("✅ 3. Devolución Elegible (Guía)", "Quiero tramitar la devolución de mi pedido ECO-10006 (Termo PROD-006). Me fue entregado, el empaque está completamente sellado y sin usar. ¿Me pueden generar la guía a Bogotá?"),
            ("🛡️ 4. Rechazo Sanitario (Sello)", "Quiero devolver el cepillo dental PROD-002 de mi pedido ECO-10002 porque no me gustó, aunque ya abrí la caja de cartón."),
            ("❓ 5. Solicitud Incompleta", "Hola, quiero devolver un producto que compré la semana pasada porque cambié de opinión. ¿Cómo hago?"),
            ("⚠️ 6. Fuera de Alcance", "Por favor cancela mi cobro bancario de $65.000 COP y reembolsa el dinero a mi tarjeta inmediatamente.")
        ]
        for etiqueta, prompt in casos_tf:
            if st.button(etiqueta, key=f"btn_tf_{etiqueta[:10]}", use_container_width=True):
                st.session_state.prompt_elegido = prompt

    with tab_t2:
        st.caption("Casos Históricos del Taller 2 (Comparativa de Evolución):")
        casos_t2 = [
            ("1. Pedido ECO-10004 y daño", "¿Qué pasó con el pedido ECO-10004 y qué hago si llegó dañado?"),
            ("2. Precio y stock PROD-009", "¿Cuál es el precio y disponibilidad del producto PROD-009?"),
            ("3. Devolver shampoo abierto", "¿Puedo devolver un shampoo sólido que ya abrí?"),
            ("4. Certificación y cuidado", "¿Qué certificaciones tiene la bolsa de algodón y cómo se cuida?"),
            ("5. Cancelar cobro bancario", "¿Puedes cancelar mi cobro bancario ahora mismo?"),
            ("6. Pedido inexistente ECO-99999", "¿Cuál es el estado del pedido ECO-99999?")
        ]
        for etiqueta, prompt in casos_t2:
            if st.button(etiqueta, key=f"btn_t2_{etiqueta[:10]}", use_container_width=True):
                st.session_state.prompt_elegido = prompt

    st.divider()

    # Visor de Devoluciones Registradas en SQLite
    st.subheader("📦 Devoluciones Radicadas (SQLite)")
    try:
        conn = sqlite3.connect(str(get_db_path()))
        devoluciones = conn.execute("SELECT radicado, codigo_pedido, sku_producto, estado_devolucion FROM devoluciones ORDER BY fecha_solicitud DESC LIMIT 5").fetchall()
        conn.close()
        if devoluciones:
            for d in devoluciones:
                st.markdown(f"**{d[0]}** | Pedido: `{d[1]}` | Estado: `{d[3]}`")
        else:
            st.info("No hay devoluciones registradas aún.")
    except Exception as e:
        st.warning("Base de datos no inicializada.")

    if st.button("🗑️ Limpiar Historial de Chat"):
        st.session_state.messages = []
        st.rerun()


# ============================================================================
# ÁREA PRINCIPAL DE CHAT
# ============================================================================
st.title("🌱 EcoMarket — Centro de Atención Inteligente")
st.caption("Asistente autónomo proactivo para consultas corporativas y automatización de devoluciones.")

if not OLLAMA_API_KEY:
    st.warning("⚠️ Por favor ingresa tu `OLLAMA_API_KEY` en la barra lateral para interactuar con EcoBot.")
    st.stop()

# Inicializar historial de mensajes
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "¡Hola! Soy **EcoBot** 🌱, el asistente de atención al cliente de **EcoMarket**.\n\nPuedo orientarte sobre nuestras políticas de sostenibilidad, consultar el estado de tus compras o gestionar la **devolución de tus pedidos** de manera automática. ¿En qué te puedo colaborar hoy?"
        }
    ]

# Renderizar mensajes anteriores
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "evidencias" in msg and msg["evidencias"]:
            with st.expander("🛠️ Herramientas MCP ejecutadas"):
                st.json(msg["evidencias"])

# Capturar nuevo prompt (por input o por botón de la barra lateral)
prompt_actual = None
if "prompt_elegido" in st.session_state and st.session_state.prompt_elegido:
    prompt_actual = st.session_state.prompt_elegido
    st.session_state.prompt_elegido = None
else:
    prompt_actual = st.chat_input("Escribe tu consulta o solicitud de devolución...")

if prompt_actual:
    st.session_state.messages.append({"role": "user", "content": prompt_actual})
    with st.chat_message("user"):
        st.markdown(prompt_actual)

    with st.chat_message("assistant"):
        with st.spinner("EcoBot está consultando la base de conocimiento y los servidores MCP..."):
            try:
                agente = compilar_agente(OLLAMA_API_KEY)
                t0 = time.time()
                resultado = agente.invoke({"consulta": prompt_actual})
                t1 = time.time()

                respuesta_texto = resultado.get("respuesta", "Sin respuesta.")
                evidencias = resultado.get("evidencia", [])

                st.markdown(respuesta_texto)
                if evidencias:
                    with st.expander(f"🛠️ Herramientas MCP ejecutadas ({len(evidencias)}) — {t1-t0:.2f}s"):
                        st.json(evidencias)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": respuesta_texto,
                    "evidencias": evidencias
                })
                st.rerun()

            except Exception as exc:
                st.error(f"Error al procesar la solicitud: {str(exc)}")
