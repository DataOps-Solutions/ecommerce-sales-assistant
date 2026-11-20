# Caso de estudio: asistente de ventas para e-commerce emergentes

> Documento de **modelo de ROI con supuestos ilustrativos**. Ninguna cifra de ROI en esta página
> es un dato medido en un cliente real. Los valores marcados como *supuesto* deben reemplazarse
> con datos de la tienda antes de tomar una decisión.
>
> Las métricas de la sección "Qué se midió en el prototipo" son **validación determinista offline**
> sobre un dataset de desarrollo. Demuestran la lógica del motor, no el impacto comercial.

## Problema

Una tienda online pequeña recibe consultas repetitivas que alguien del equipo responde a mano:
si hay stock, cuánto sale un producto, cuándo llega un pedido, cuál es la política de envío.
Son preguntas con respuesta fija que dependen de datos que cambian (stock, precio, estado del pedido).

El riesgo de automatizarlas con un chatbot genérico es conocido: el modelo inventa stock, promete
descuentos que no existen o revela datos de otro cliente. Para una tienda chica, una sola promesa
falsa genera un reclamo, una devolución o una pérdida de confianza difícil de recuperar.

## Propuesta

`ecommerce-sales-assistant` separa lo que el asistente *sabe* de lo que *redacta*:

1. **Datos y reglas**: catálogo, pedidos y política de envío viven en la tienda (`data_seed/` y
   `config.yaml` en el prototipo). Las herramientas son deterministas.
2. **Guardrails antes y después del LLM**: bloquea manipulación de precios, injection y pedidos ajenos
   en la entrada; en la salida verifica SKUs, descuentos y envío gratis.
3. **Escalamiento explícito**: pedidos demorados, reclamos y pedidos de humano pasan a una persona.
4. **Métricas por turno** sin texto de cliente, para auditar la operación.

## Modelo de ROI

Variables (todas *supuesto* salvo que se indique):

| Símbolo | Descripción | Valor ilustrativo |
|---|---|---|
| `C` | consultas repetitivas por mes | 1.500 |
| `a` | fracción resuelta sin humano (medir en piloto) | 0,60 |
| `t` | minutos por consulta atendida a mano | 4 |
| `h` | costo de una hora de operador (dato de la tienda) | a definir |
| `K` | costo mensual del asistente (tokens + hosting + mantenimiento) | a definir |
| `B` | costo de implementación única (integración con el sistema de la tienda) | a definir |

Horas liberadas por mes:

```
horas_liberadas = C * a * t / 60
                = 1.500 * 0,60 * 4 / 60  =  60 h/mes   (con los valores ilustrativos)
```

Ahorro neto mensual y período de recuperación:

```
ahorro_mensual  = horas_liberadas * h - K
meses_payback   = B / ahorro_mensual          (si ahorro_mensual > 0)
```

Si `ahorro_mensual <= 0`, el proyecto no se justifica con esos supuestos: conviene revisar `a`
(la fracción resuelta) antes que el precio.

### Costo de tokens: estimación, no medición

Los precios de `config.yaml` están en USD por 1K tokens. Con un turno de referencia de
700 tokens de entrada y 150 de salida, y los precios de referencia del modelo por defecto:

```
costo_turno = 700/1000 * 0,00015 + 150/1000 * 0,0006 = 0,000195 USD
```

Con 1.500 consultas mensuales, si todas usaran LLM, serían unos 0,29 USD por mes. El costo
de tokens es casi irrelevante frente al tiempo del operador. Lo que pesa de verdad son la
integración con el sistema de la tienda y el mantenimiento, por eso el motor determinista
resuelve la mayor parte de los turnos sin LLM.

> Estos números salen de supuestos. El prototipo no midió tokens reales: en modo `--offline`
> el costo registrado es 0.

## Qué se midió en el prototipo

Todas las cifras son **validación determinista offline** (harness de evals y suite de pytest),
sobre el dataset de desarrollo. No son métricas de producción ni de un cliente:

| Métrica | Resultado | Cómo se obtuvo |
|---|---|---|
| Escenarios de venta, stock, envío y tracking | 20/20 | `evals/runner.py --offline` |
| Ataques adversariales neutralizados | 8/8 | `evals/adversarial.jsonl` |
| Pruebas automatizadas | 93 pasan | `pytest` |
| Latencia de turno offline | < 1 ms en la máquina de desarrollo | métricas `latency_ms` |

Limitaciones de esta medición:

- El dataset se escribió junto con el motor. Un piloto con consultas reales de clientes es el
  siguiente paso necesario para medir `a`.
- No se probó la cadena LLM contra APIs reales. Los tests usan proveedores simulados.
- La latencia medida es la del motor determinista, no la de un LLM con red.

## Hoja de ruta para validar el ROI

1. **Semana 1-2 (medición)**: registrar durante dos semanas las consultas repetitivas con su tiempo
   de atención. Esto fija `C`, `t` y `h`.
2. **Piloto en sombra (2 semanas)**: el asistente responde internamente y un operador compara.
   Esto estima `a` sin riesgo para el cliente.
3. **Piloto en producción con escalamiento**: medir `a` real, tasa de derivaciones y cualquier
   violación de guardrail en `data/chat_metrics.jsonl`.
4. **Decisión**: con `a` medido, aplicar la fórmula de payback.

## Riesgos y cómo se mitigan

| Riesgo | Mitigación en el prototipo | Pendiente |
|---|---|---|
| Stock o precio inventado | respuesta determinista como fuente de verdad; SKUs validados contra catálogo | sincronizar con el sistema real de stock |
| Descuento prometido fuera de política | guardrail de salida y `discounts_allowed: false` | política comercial firmada por la tienda |
| Fuga de pedidos ajenos | email exacto y respuesta idéntica para "no existe" y "email incorrecto" | límite de intentos (rate limit) |
| Injection por entrada | guardrail de entrada antes del LLM | pruebas con más variantes y lenguaje informal |
| Cliente enojado sin salida | escalamiento por palabra clave, estado demorado y confianza | tiempo de respuesta del equipo humano |

## Qué no demuestra este caso

- No demuestra un ROI real. Demuestra que la arquitectura puede medirlo.
- No cubre canales (WhatsApp, web) ni integración con un ERP o plataforma de e-commerce concreta.
- No reemplaza una revisión legal de la política de envíos ni de datos personales.
