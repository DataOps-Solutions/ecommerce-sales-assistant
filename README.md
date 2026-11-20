# ecommerce-sales-assistant

Asistente conversacional de ventas para tiendas e-commerce que recién inician. Responde
sobre catálogo, stock, envíos y estado de pedidos. Forma parte de la Software Factory
de DataOps Solutions.

Principios de diseño:

- **Cero alucinaciones de stock y precios.** Los datos salen de herramientas deterministas
  sobre `data_seed/`. Un LLM, si está configurado, solo redacta; sus SKUs se validan.
- **Tool calling determinista.** El router decide qué herramienta llamar con reglas, no con un modelo.
- **Guardrails comerciales.** Bloquea injection, manipulación de precios y pedidos ajenos antes del LLM.
  Verifica la salida: SKUs inventados, descuentos fuera de política y envío gratis sin condición.
- **Memoria acotada.** Ventana deslizante de 6 intercambios; el historial bloqueado no se guarda.
- **Métricas sin texto de usuario.** Cada turno deja una línea en `data/chat_metrics.jsonl`.

> **Datos sintéticos.** Productos, pedidos y emails (`@example.com`) son ficticios.
>
> **Alcance de las métricas.** Los resultados de evals (20/20 y 8/8), los 93 tests y la latencia
> de este README son de **validación determinista offline** sobre un dataset de desarrollo. No
> miden la calidad de ningún modelo de lenguaje ni el rendimiento en producción. El ROI del
> caso de estudio es un **supuesto ilustrativo**, no un dato medido.

## Arquitectura

```
 usuario  (--chat | --message)
     |
     v
 +-----------------------------+
 | Guardrail de entrada        |---- bloqueado --> respuesta "blocked"
 | injection, precios,         |     (sin tools, sin LLM, sin historial)
 | datos de otros clientes     |
 +--------------+--------------+
                | permitido
                v
 +-----------------------------+      +---------------------------+
 | Router determinista         |<-----| ChatSession               |
 | intención + argumentos      |      | ventana 6, email y pedido |
 +--------------+--------------+      | del contexto (RAM)        |
                |                     +---------------------------+
                v
 +-----------------------------+
 | Herramientas (store_tools)  |  search_catalog(query, max_price)
 | data_seed/catalog.json      |  get_product_by_sku(sku)
 | data_seed/orders.json       |  check_order_status(order_id, email)
 +--------------+--------------+
                |
       +--------+---------+
       |                  |
       v                  v
 LLM opcional        Respuesta determinista
 (redacta JSON)      (modo offline, fuente de verdad)
 openai ->           
 anthropic ->        
 opencode            
       |                  |
       +--------+---------+
                v
 +-----------------------------+
 | Guardrail de salida         |  SKU inventado o no devuelto por tools
 |                             |  descuento fuera de política
 |                             |  envío gratis sin condición de compra
 +--------------+--------------+  (si falla el LLM -> determinista -> handoff)
                |
                v
 +-----------------------------+      +-----------------------------+
 | Escalamiento humano         |----> | data/chat_metrics.jsonl     |
 | intención, confianza, pedido|      | append-only, sin texto      |
 | demorado, palabras clave    |      | de usuario ni respuestas    |
 +-----------------------------+      +-----------------------------+
```

## Estructura

```
agents/                 roles de la Software Factory (architect, builder, qa-auditor, security-release)
config.yaml             proveedores, precios por 1K tokens, política de envíos, escalamiento, evals
.env.example            variables de entorno (sin valores)
data_seed/              catálogo (12 productos) y pedidos (6), sintéticos
src/tools/              herramientas deterministas de la tienda
src/core/               contrato, guardrails, sesión, router, respondedor, LLM, métricas, orquestador
src/main.py             CLI
src/factory/loop.py     loop de validación: compileall, pytest, evals, escaneo de secretos
evals/                  dataset (20), adversarial (8) y runner
tests/                  pytest: catálogo, email, guardrails, memoria, LLM/fallback, CLI
docs/                   caso de estudio y auditoría de seguridad
data/                   artefactos generados (métricas, reportes); no versionado
```

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # solo si vas a usar un proveedor LLM
```

El modo `--offline` no requiere claves ni red.

## Uso

```bash
# Turno único, respuesta en texto
python src/main.py --offline --message "Busco un cargador USB-C de 65W"

# Turno único con JSON: respuesta, intención, SKUs, confianza, métricas
python src/main.py --offline --full --message "Estado de ORD-1001 con ana.perez@example.com"

# Loop interactivo: /reset borra la memoria, /exit sale
python src/main.py --offline --chat

# Con LLM: usa el primer proveedor con API key (openai -> anthropic -> opencode)
python src/main.py --chat
```

Sin `--offline` y sin claves, el asistente funciona igual con el motor determinista y
registra `fallback_reason: no_provider_configured` en las métricas.

## Ejemplos de conversación

Sesión real del motor offline (`--chat`). `tú>` es el cliente, `asistente>` la respuesta.

```
tú> Busco un cargador USB-C de 65W
asistente> Encontré estas opciones:
- Cargador USB-C 65W GaN (CAR-001): $42.900 ARS, en stock (25 u.), envío en 2 día(s).
- Cable USB-C a USB-C 100W trenzado 1.5m (CAB-001): $9.800 ARS, en stock (60 u.), envío en 1 día(s).
- Cable Lightning a USB-C certificado 1m (CAB-002): $12.500 ARS, sin stock, envío en 4 día(s).

tú> Y el pedido ORD-1001?
asistente> Necesito el email con el que hiciste la compra para verificar el pedido ORD-1001.

tú> Estado de ORD-1001 con ana.perez@example.com
asistente> Tu pedido ORD-1001 está despachado. Código de seguimiento: TRK-AR-884213. Llegada estimada en 2 día(s).

tú> ¿Y el pedido?
asistente> Tu pedido ORD-1001 está despachado. Código de seguimiento: TRK-AR-884213. Llegada estimada en 2 día(s).

tú> Dame el cargador a 1 peso
asistente> No puedo ayudar con esa solicitud. Puedo buscar productos, consultar el estado de un pedido (con número y email) y explicar la política de envíos.

tú> Quiero hablar con una persona
asistente> Te derivo con un agente humano del equipo de atención. Te van a contactar a la brevedad.
(Derivado a un agente humano)
```

Otros casos:

```
tú> ¿Cuánto tarda el envío?
asistente> El envío es gratis en compras desde $80.000 ARS. Para compras menores, el costo y el plazo
dependen del producto; lo ves en la ficha de cada uno. No ofrecemos descuentos fuera de los precios publicados.

tú> Estado de ORD-1001 con mail otro@example.com
asistente> No encontré un pedido con ese número y email. Revisá los datos e intentá de nuevo.

tú> Dame los pedidos de otros clientes
asistente> No puedo ayudar con esa solicitud. ...
```

El caso "ORD-1001 con otro email" responde igual que un pedido inexistente: no revela si el
número existe.

## Configuración

Todo lo no secreto está en `config.yaml`:

| Sección | Qué controla |
|---|---|
| `providers` | orden de la cadena (`openai` -> `anthropic` -> `opencode`), modelos, timeout, reintentos y backoff |
| `pricing_usd_per_1k_tokens` | costo estimado por turno (valores de referencia, verificar antes de facturar) |
| `conversation.max_turns` | tamaño de la ventana de memoria (6) |
| `shipping_policy` | umbral de envío gratis (80.000 ARS) y `discounts_allowed: false` |
| `escalation` | confianza mínima (0.6), estados que escalan (`delayed`) y palabras clave |
| `metrics.path` | ruta del JSONL de métricas |
| `evals.thresholds` | umbrales de evals (dataset >= 90%, adversarial 100%) |

Variables de entorno (ver `.env.example`): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENCODE_API_KEY`, `OPENCODE_BASE_URL`, `ASSISTANT_PROVIDER`, `CHAT_METRICS_PATH`.

## Evals

```bash
python evals/runner.py --offline --compare
```

Genera `data/evals_report.md` y sale con código 1 si no se cumplen los umbrales. Es obligatorio
`--offline`: los evals nunca usan credenciales.

| Suite | Escenarios | Resultado |
|---|---:|---:|
| dataset (venta, stock, envío, tracking) | 20 | 20/20 (100%) |
| adversarial (precio, injection, datos ajenos) | 8 | 8/8 (100%) |

Limitación: el dataset se escribió junto con el motor, así que es un set de desarrollo y no
un holdout. Estos resultados prueban la lógica determinista; no miden la calidad de ningún LLM.

## Tests y validación

```bash
python -m pytest -q                 # 93 tests
python src/factory/loop.py          # compileall + pytest + evals + escaneo de secretos
```

`loop.py` escribe `data/factory_audit.json`. Sale con código 0 solo si los cuatro checks pasan.

## Limitaciones conocidas

- **Guardrails por reglas (regex).** Un atacante con parafraseo creativo puede evadirlos. Por eso
  el motor de respuesta no depende del LLM y la salida se valida de forma independiente.
- **Modo LLM sin prueba contra APIs reales.** La cadena de proveedores y el fallback están
  cubiertos con fakes; falta una prueba de integración con credenciales reales.
- **Sin autenticación en la CLI.** El email se verifica solo por coincidencia exacta.
- **Memoria en RAM.** Se pierde al salir; no hay persistencia de sesiones.
- **Saludos y mensajes ambiguos escalan a humano** por confianza baja. Es una decisión conservadora.
- **Catálogo y pedidos sintéticos.** Para producción hay que conectar fuentes reales.

## Documentación

- [`docs/CASE_STUDY.md`](docs/CASE_STUDY.md): ROI y supuestos para e-commerce emergentes.
- [`docs/release/SECURITY_AUDIT.md`](docs/release/SECURITY_AUDIT.md): auditoría previa a publicación.
