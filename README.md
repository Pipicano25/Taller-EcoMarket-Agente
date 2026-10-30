# 🌱 EcoMarket — Agente de IA para Automatización de Atención al Cliente y Devoluciones

<a href="https://colab.research.google.com/github/Pipicano25/Taller-EcoMarket-Agente/blob/main/proyecto_final/EcoMarket_Agente.ipynb" target="_parent"><img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab"/></a>

**Autores:** Anderson Pipicano, Fredy Alvarez  
**Asignatura:** Inteligencia Artificial Generativa — Maestría en Inteligencia Artificial  
**Modelo Generativo:** `glm-5.3-flash` (vía Ollama Cloud)  
**Embeddings:** `BAAI/bge-m3` (1024 dimensiones)  
**Marco de Agentes:** LangGraph (`StateGraph`)  
**Protocolo de Herramientas:** FastMCP (*Model Context Protocol*)  
**Bases de Datos:** SQLite (`ecomarket.db`) y ChromaDB (`ecomarket_kb`)  
**Despliegue Web:** Streamlit + Cloudflare Tunnel (`cloudflared`)  

---

## 📌 Descripción del Proyecto

Este repositorio contiene la implementación integral del **Proyecto Final**, en el cual se evolucionó el asistente pasivo de recuperación documental (**RAG**) desarrollado en el Taller 2 hacia un **Agente Inteligente Autónomo y Proactivo**, capaz de:

1. **Atender consultas informativas y normativas** recuperando fragmentos semánticos precisos desde ChromaDB con embeddings multilingües `BAAI/bge-m3`.
2. **Consultar de forma determinista el estado de pedidos e inventario** en una base de datos relacional SQLite (`ecomarket.db`).
3. **Validar la elegibilidad legal y sanitaria de devoluciones** según la **Ley 1480 del Estatuto del Consumidor (retracto de 30 días)** y la **Sección 3 de la Política Sanitaria** (bloqueo preventivo de productos de higiene destapados/usados).
4. **Emitir radicados formales (`RET-2026-XXXX`) y generar guías de retorno logístico** integrando trazabilidad transaccional en SQLite.
5. **Desplegar una interfaz conversacional interactiva en Streamlit**, accesible públicamente mediante túneles seguros de Cloudflare.

---

## 🏗️ Arquitectura del Sistema

```
                      ┌─────────────────────────────────────────┐
                      │          Cliente / Interfaz Web         │
                      │          (Streamlit Conversacional)     │
                      └────────────────────┬────────────────────┘
                                           │
                                           ▼
                      ┌─────────────────────────────────────────┐
                      │    Orquestador Agéntico (LangGraph)     │
                      │  START -> Planificador -> Ejecutor      │
                      │        -> Responder -> END              │
                      └────────────────────┬────────────────────┘
                                           │
            ┌──────────────────────────────┼──────────────────────────────┐
            ▼                              ▼                              ▼
 ┌──────────────────────┐      ┌──────────────────────┐      ┌──────────────────────┐
 │ Servidor MCP Datos   │      │ Servidor MCP Retorno │      │ Servidor MCP RAG     │
 │ (datos_mcp_server)   │      │ (devoluciones_server)│      │ (conocimiento_server)│
 └──────────┬───────────┘      └──────────┬───────────┘      └──────────┬───────────┘
            │                             │                             │
            ▼                             ▼                             ▼
 ┌────────────────────────────────────────────────────┐      ┌──────────────────────┐
 │             Base de Datos Relacional               │      │ Base de Conocimiento │
 │               SQLite (ecomarket.db)                │      │ Vectorial (ChromaDB) │
 │  - pedidos (11 órdenes)                            │      │ - política_devoluc.  │
 │  - inventario (12 productos)                       │      │ - manual_sostenib.   │
 │  - devoluciones (radicados transaccionales)        │      │ - preguntas_frec.    │
 └────────────────────────────────────────────────────┘      └──────────────────────┘
```

---

## 📂 Estructura del Repositorio

```text
├── context/                                      # Fuentes de datos y documentos de referencia
│   ├── inventario_productos.csv                  # Catálogo de 12 productos con precios y banderas sanitarias
│   ├── manual_sostenibilidad_y_operaciones.pdf   # Manual operativo y consejos ecológicos
│   ├── pedidos.txt                               # Historial de 11 órdenes de compra
│   ├── politica_devoluciones.pdf                 # Política corporativa de plazos y restricciones
│   └── preguntas_frecuentes.json                 # Base de preguntas y respuestas frecuentes
│
├── proyecto_final/                               # Código fuente y artefactos del agente
│   ├── EcoMarket_Agente.ipynb                    # Notebook interactivo (Google Colab y local)
│   ├── app.py                                    # Aplicación web conversacional en Streamlit
│   ├── requirements.txt                          # Dependencias y librerías del proyecto
│   └── mcp_servers/                              # Arquitectura modular de servidores MCP
│       ├── __init__.py
│       ├── seed_datos.py                         # Ingesta relacional SQLite (ecomarket.db)
│       ├── datos_mcp_server.py                   # Herramientas: consultar_pedido, consultar_inventario
│       ├── devoluciones_mcp_server.py            # Herramientas: verificar_elegibilidad, generar_etiqueta
│       └── conocimiento_mcp_server.py            # Herramienta: buscar_conocimiento (RAG ChromaDB)
│
├── caso_de_estudio_taller_final.md               # Informe técnico y académico detallado (Fases 1, 2, 3 y 4)
└── README.md                                     # Documentación principal del repositorio
```

---

## 🚀 Instrucciones de Ejecución

### Opción 1: Ejecución Inmediata en Google Colab (Recomendada)

1. Haz clic en el botón superior **[Open In Colab](https://colab.research.google.com/github/Pipicano25/Taller-EcoMarket-Agente/blob/main/proyecto_final/EcoMarket_Agente.ipynb)**.
2. Obtén una API Key gratuita en [Ollama Cloud](https://ollama.com).
3. En el menú de Colab, selecciona **Entorno de ejecución > Ejecutar todas**.
4. Al llegar a la Celda 19, se descargará automáticamente el binario de Cloudflare Tunnel y se generará una URL pública segura (ej. `https://xxxx.trycloudflare.com`) para interactuar con la aplicación web de Streamlit.

### Opción 2: Ejecución Local

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/Pipicano25/Taller-EcoMarket-Agente.git
   cd Taller-EcoMarket-Agente
   ```

2. **Crear y activar un entorno virtual:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # En Linux/macOS
   .venv\Scripts\activate     # En Windows
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r proyecto_final/requirements.txt
   ```

4. **Inicializar la base de datos relacional SQLite:**
   ```bash
   python -c "from proyecto_final.mcp_servers.seed_datos import seed_database; seed_database()"
   ```

5. **Lanzar la aplicación web con Streamlit:**
   ```bash
   streamlit run proyecto_final/app.py
   ```

---

## 🧪 Casos de Prueba y Evaluación Comparativa

En [`caso_de_estudio_taller_final.md`](caso_de_estudio_taller_final.md) se encuentra documentada la evaluación comparativa entre la versión RAG pasiva del Taller 2 y la arquitectura agéntica del Taller Final sobre 6 escenarios operativos:

| # | Escenario Evaluado | Consulta del Cliente | Decisión y Comportamiento Agéntico |
| :---: | :--- | :--- | :--- |
| **1** | **Consulta Normativa RAG** | *¿Cuáles son los plazos y condiciones generales para solicitar una devolución?* | Recupera la política en ChromaDB y responde con base legal (30 días Ley 1480). |
| **2** | **Consulta Determinista SQL** | *¿Qué precio tiene y qué certificaciones posee el producto PROD-003?* | Consulta SQLite por clave primaria (`PROD-003`). Cero alucinaciones en stock (\$45.000 COP, certificación GOTS). |
| **3** | **Devolución Elegible (Trámite)** | *Quiero tramitar la devolución de mi pedido ECO-10006 (Termo PROD-006 sellado a Bogotá).* | Valida plazo y empaque intacto, genera radicado `RET-2026-XXXX`, emite guía de Servientrega y registra en SQLite. |
| **4** | **Rechazo Sanitario Fundamentado** | *Quiero devolver el cepillo dental PROD-002 de mi pedido ECO-10002 porque no me gustó, aunque ya abrí la caja.* | Guardrail normativo: detecta `EXCEPCION_SANITARIA_SELLO_ROTO`, bloquea la emisión de guía y ofrece recomendaciones del manual. |
| **5** | **Solicitud Incompleta** | *Hola, quiero devolver un producto que compré la semana pasada. ¿Cómo hago?* | No ejecuta herramientas a ciegas. Solicita amablemente el número de pedido `ECO-XXXXX` y estado del empaque. |
| **6** | **Operación Fuera de Alcance** | *Por favor cancela mi cobro bancario de $65.000 COP inmediatamente.* | Reconoce ausencia de permisos transaccionales directos bancarios y orienta al canal financiero oficial. |

---

## 📄 Licencia y Aspectos Académicos

Este proyecto ha sido desarrollado exclusivamente con fines académicos para la asignatura de **Inteligencia Artificial Generativa** de la Maestría en Inteligencia Artificial. Todos los datos de demostración son simulados y diseñados para validar arquitecturas agénticas en escenarios empresariales.
