# Auditoría de seguridad y release: ecommerce-sales-assistant

Fecha de referencia: 2026-11-20. Alcance: carpeta `ecommerce-sales-assistant/` completa, en su
estado actual, sin historial propio de git (ver hallazgo M-01).

## Veredicto

**LISTO PARA PUBLICAR**, con tres pendientes no bloqueantes (M-01, M-02, M-03).

El repositorio no contiene credenciales, no contiene datos reales de clientes y no usa patrones
de ejecución peligrosa. Los pendientes son de operación, no de código que exponga datos.

## Verificaciones ejecutadas

| Check | Comando o método | Resultado |
|---|---|---|
| Sintaxis | `python -m compileall -q src` (vía loop) | PASS |
| Tests | `python -m pytest -q` (vía loop) | PASS, 93 tests |
| Evals | `python evals/runner.py --offline --compare` (vía loop) | PASS, dataset 20/20, adversarial 8/8 |
| Escaneo de secretos | `src/factory/loop.py`, reglas `aws_secret`, `openai_style_key`, `hardcoded_api_key` | PASS, sin hallazgos |
| Patrones peligrosos | búsqueda en `src/` y `evals/` de `eval(`, `exec(`, `pickle`, `shell=True`, `subprocess`, `os.system` | sin hallazgos fuera de `src/factory/loop.py` |
| Variables de entorno | cruce de `.env.example` contra el código | 6 de 6 se usan |
| Ignorados por git | `git check-ignore` sobre `.env` y `data/` | ambos excluidos por `.gitignore` |
| Archivos sensibles | `.env`, `*.pem`, `*.key` | ninguno presente |
| Privacidad de métricas | test `test_metrics_are_append_only_and_contain_no_user_text` | el JSONL no contiene texto de usuario, emails ni respuestas |
| Filtrado de pedidos | tests de `check_order_status` | email incorrecto y pedido inexistente devuelven la misma respuesta; nunca se devuelve el email |

## Hallazgos

Ordenados por severidad.

### Críticos

Ninguno.

### Altos

Ninguno.

### Medios

**M-01. El proyecto no tiene historial propio.** La carpeta está dentro del repositorio `/Henry`
como directorio sin trackear (`?? ecommerce-sales-assistant/`). No hay commits de este proyecto,
así que no se pudo revisar `git log -p` por secretos eliminados. Acción: antes de publicar,
inicializar el repositorio del proyecto o confirmar en el repositorio padre que solo se
versionan los archivos de esta carpeta, y repetir el escaneo sobre el historial.

**M-02. Sin límite de intentos en la consulta de pedidos.** `check_order_status` exige email exacto,
pero no limita intentos. Los números de pedido son secuenciales (`ORD-1001`...). Un atacante con una
lista de emails podría probar combinaciones. No se filtra ningún dato sin el email correcto, pero
la consulta no tiene freno. Acción: rate limit por sesión o por origen cuando el asistente se
exponga a internet.

**M-03. Guardrails por expresiones regulares.** Las reglas de `src/core/guardrails.py` cubren
variantes conocidas en español e inglés. Un atacante que parafrasee puede evadir la regla de
entrada. Mitigación actual: el motor determinista no depende del LLM, y la salida se valida de forma
independiente (SKU existente, descuento, envío gratis). Acción: agregar casos adversariales nuevos
al dataset en cada iteración.

### Bajos

**B-01. Modo LLM sin prueba de integración.** La cadena OpenAI -> Anthropic -> OpenCode y el
fallback están probados con proveedores simulados. No se llamó a ninguna API real en esta
auditoría. Pendiente: prueba con credenciales de un entorno de staging.

**B-02. Sin autenticación en la CLI.** La CLI es local. Cualquier usuario con acceso a la consola
puede consultar cualquier pedido si conoce el email. Aceptable para una herramienta local; no
aceptable para un canal público sin autenticación del cliente.

**B-03. Memoria en RAM.** El email y el número de pedido recordados en la sesión se pierden al
salir. No se escriben en disco. Ningún archivo persistente guarda contenido de conversación.

**B-04. Derivación por palabra clave.** Mensajes ambiguos (por ejemplo, un saludo) escalan a humano
por confianza baja. Es conservador y genera carga operativa; ajustar con datos del piloto.

**B-05. Precios de referencia.** `pricing_usd_per_1k_tokens` son valores de referencia, marcados en
`config.yaml`. Verificar contra la tabla oficial del proveedor antes de facturar.

## Revisión de checklist

1. **Secretos**: ninguno en el código, la configuración ni la documentación. `.env.example` tiene
   valores vacíos. `config.yaml` solo contiene nombres de variables, no valores.
2. **Historial**: no aplicable todavía (M-01).
3. **Archivos sensibles**: no hay `.env`, claves ni dumps. `.gitignore` excluye `.env`, `.env.*`
   (salvo `.env.example`), `.venv/`, `data/`, cachés de Python y `*.pem`, `*.key`.
4. **`.env.example`**: lista las 6 variables, todas usadas en el código (`llm.py`, `config.py`,
   `config.yaml` para los nombres de variables).
5. **`.gitignore`**: cubre `.env`, `.venv/`, `data/`, `__pycache__/`, `.pytest_cache/`.
6. **Inyecciones**: sin SQL, sin `eval`/`exec`, sin `pickle`, sin `shell=True`. El único `subprocess`
   está en el loop de la fábrica con argumentos en lista. Las entradas del usuario nunca llegan a
   un shell ni a un intérprete.
7. **Permisos**: sin scripts con permisos excesivos. Las escrituras van solo a `data/` (métricas y
   reportes) y a la ruta de `CHAT_METRICS_PATH`, que la configura quien opera el sistema.
8. **Datos de clientes**: el catálogo y los pedidos son sintéticos. Los emails usan `example.com`,
   dominio reservado. Las métricas no guardan contenido de conversación.

## Datos personales en el flujo

- Entrada: el email y el número de pedido que escribe el cliente. Se usan para la consulta y, si
  la sesión está activa, se recuerdan en RAM.
- Salida al LLM (solo en modo LLM): el mensaje, el historial de la ventana, el plan de herramientas
  y los datos de productos o del pedido verificado. El email del cliente no se envía en
  `tool_results`. El mensaje sí se envía, por lo que el proveedor LLM recibe el email si el cliente
  lo escribe en el chat. Pendiente: revisar el acuerdo de tratamiento de datos con cada proveedor.
- Persistencia: solo metadatos en `data/chat_metrics.jsonl` (intención, SKUs, tokens, costo,
  latencia, violaciones, errores de proveedor). No se guardan mensajes ni respuestas.

## Resumen técnico para README (texto listo para copiar)

> ecommerce-sales-assistant es un asistente de ventas para tiendas e-commerce. Responde sobre
> catálogo, stock, envíos y pedidos con datos de herramientas deterministas, no con texto generado
> por un modelo. Un modelo de lenguaje, si está configurado, solo redacta la respuesta, y sus SKUs
> se validan contra el catálogo. Los guardrails bloquean manipulación de precios, injection y
> pedidos de otros clientes antes de cualquier llamada externa, y validan la salida contra
> descuentos no autorizados. Cada turno deja una métrica sin contenido de conversación.

## Puntos para el caso de estudio

- Arquitectura: router determinista + herramientas + LLM opcional que solo redacta + guardrails de
  entrada y salida + escalamiento + métricas append-only.
- Guardrails implementados: 4 categorías de entrada (injection, precios, datos ajenos, longitud),
  y 4 controles de salida (SKU inventado, SKU no devuelto por herramientas, descuento fuera de
  política, envío gratis sin condición).
- Métricas medidas (offline, dataset de desarrollo): 20/20 escenarios, 8/8 adversariales, 88
  tests, latencia p95 de 0.13 ms en el motor determinista.
- Limitación a declarar: el dataset es de desarrollo, no un holdout; la cadena LLM no se probó
  contra APIs reales.
