# Proyecto: Generador de cursos con IA para Odoo eLearning

## Qué es esto

Pipeline externo (Python) que convierte material fuente (PDFs, normativas técnicas,
manuales) en cursos completos publicados en Odoo eLearning, usando la API de Claude
(Anthropic) para generar el contenido y XML-RPC para cargarlo en Odoo.

Cliente: empresa atendida por GerenciAndo Canales (consultora de estrategia comercial
e IA, Argentina). El material puede ser normativa técnica donde **la precisión importa**:
el contenido generado debe estar fundado en el material fuente, sin inventar.

**Flujo:** `PDF(s) → extracción de texto → Claude (2 pasadas) → JSON validado →
preview de revisión humana → carga en Odoo vía XML-RPC → curso publicado`

**Uso final:**
```bash
python main.py input/normativa.pdf --titulo "Seguridad Eléctrica" [--publicar] [--skip-review]
```

## Decisiones de arquitectura YA TOMADAS (no rediscutir, implementar)

1. **NO es un módulo de Odoo.** Es un programa externo. Odoo no se toca, no se
   instala nada dentro de Odoo. La integración es 100% vía API externa XML-RPC.
2. **Instancia Odoo:** Odoo Online (SaaS) plan gratuito "One App Free", versión
   `saas-19.3`, única app instalada: eLearning (`website_slides`).
   - VALIDADO empíricamente (04/07/2026): la API XML-RPC funciona completa en este
     plan (authenticate, search_read, create, unlink probados OK) aunque la
     documentación dice que no está incluida en planes gratuitos.
   - **Riesgo conocido y aceptado para desarrollo:** Odoo puede bloquear la API de
     este plan en cualquier momento sin aviso. Para producción se decidirá luego:
     seguir en el plan gratuito (riesgo comunicado al cliente) o migrar a Odoo
     Community self-hosted en VPS con Docker (donde la API está garantizada).
     El código debe ser **agnóstico de la instancia**: URL/DB/credenciales solo
     desde `.env`, nunca hardcodeadas. El mismo código debe funcionar en ambas.
3. **IA de generación:** API de Claude (Anthropic). Modelo por defecto:
   `claude-sonnet-4-6` (configurable por env var `CLAUDE_MODEL`). Salida
   estructurada: pedir JSON puro y validar contra los schemas de `pipeline/schemas.py`.
   - Fallback TEMPORAL de desarrollo (decidido 04/07/2026, mientras no hay key
     de Anthropic): `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` en `.env` usa la
     API de Gemini con los mismos prompts/schemas/validación. Volver a Claude =
     comentar `LLM_PROVIDER` y setear `ANTHROPIC_API_KEY`. No es la decisión
     de producción.
4. **Generación en 2 pasadas** (nunca todo el curso en una sola llamada):
   - Pasada 1 (estructura): recibe TODO el material → devuelve JSON con título,
     objetivos, sesiones, temas por sesión y qué fragmentos fuente cubre cada sesión.
   - Pasada 2 (contenido): UNA llamada POR SESIÓN, que recibe SOLO los fragmentos
     fuente asignados a esa sesión → devuelve HTML de la lección + quiz en JSON.
   - Razón: grounding. Cada sesión se genera con su material fuente adelante para
     minimizar alucinaciones. Regla dura en los prompts: no afirmar nada que no
     esté en el material; citar artículo/sección de la norma cuando aplique; si el
     material no cubre algo, marcarlo "(a confirmar)" en vez de inventarlo.
5. **Formato de cada sesión en Odoo** (decidido con el usuario):
   - 1 slide tipo **artículo** con HTML brandeado (contenido principal, responsive)
   - 1 slide tipo **documento** con PDF brandeado descargable (mismo contenido,
     material de estudio) — módulo `pipeline/pdf_brand.py`, puede quedar para una
     segunda iteración si complica (feature-flag `--no-pdf`)
   - 1 quiz (preguntas `slide.question` + respuestas `slide.answer`) asociado a la
     sesión. En Odoo el quiz vive DENTRO de un slide, verificar en saas-19.3 si
     conviene quiz dentro del slide artículo o un slide separado de categoría quiz.
6. **Revisión humana antes de publicar:** `preview.py` genera un HTML único con
   todo el curso (lecciones + quizzes con respuestas correctas marcadas) para que
   un humano lo apruebe. Por defecto el curso se carga como NO publicado
   (`is_published=False`); `--publicar` lo publica directo.
7. **Branding:** HTML de las lecciones con estilos inline (sin JS, sin CSS externo:
   limitación de Odoo). Colores/logo del cliente se configuran en
   `pipeline/branding.py` como constantes (placeholder hasta tener el manual de
   marca del cliente). El branding de la plataforma (logo del sitio, colores del
   theme, portada de cursos) se hace UNA vez a mano en el editor web de Odoo.

## Modelo de datos de Odoo eLearning (website_slides)

- `slide.channel` = curso. Campos clave: `name`, `description`, `is_published`,
  `enroll` (política inscripción), `visibility`.
- `slide.slide` = contenido/lección. Campos clave: `name`, `channel_id`,
  `slide_category` (article/document/video/infographic/quiz — VERIFICAR valores
  exactos en saas-19.3), `html_content` (para artículos), `binary_content` o
  similar (base64, para PDFs), `is_category` (True = es un separador de sección),
  `sequence` (orden), `is_published`.
- Secciones: son registros de `slide.slide` con `is_category=True`; los slides
  siguientes en `sequence` cuelgan de esa sección.
- `slide.question` = pregunta de quiz. Campos: `question`, `slide_id`, `sequence`.
- `slide.answer` = opción de respuesta. Campos: `question_id`, `text_value`,
  `is_correct`, `comment` (feedback al participante).

✅ **HECHO (04-05/07/2026):** `fields_get.py` corrido contra saas-19.3 (output en
`scripts/fields_output.json`, gitignored — regenerar si cambia la instancia) y
`loader.py` ajustado y verificado en vivo. Hallazgos clave ya aplicados:
`create` con lista devuelve lista (el wrapper desempaqueta), `channel_type` es
requerido, `description` es html, quiz-sobre-artículo confirmado, `enroll` solo
acepta public/invite. Detalle completo en README.md sección 11.

## Estructura del repo

```
odoo-elearning-ai/
├── CLAUDE.md            ← este archivo
├── README.md            ← documentación completa para humanos (leerla: está al día)
├── .env.example         ← plantilla de credenciales (NUNCA commitear .env real)
├── requirements.txt
├── main.py              ← CLI orquestador
├── webapp.py            ← interfaz web local (Flask, puerto 8000)
├── assets/              ← logo master + fuentes Roboto para los PDFs
├── pipeline/
│   ├── __init__.py
│   ├── extract.py       ← PDF → texto estructurado (PyMuPDF), chunking por secciones
│   ├── generate.py      ← llamadas a Claude API (pasada 1 y pasada 2)
│   ├── prompts.py       ← system prompts de ambas pasadas (ESPAÑOL, ya redactados)
│   ├── schemas.py       ← JSON schemas de validación de las salidas de Claude
│   ├── branding.py      ← paleta, logo, plantilla HTML de lección
│   ├── preview.py       ← genera output/preview_<curso>.html para revisión
│   ├── pdf_brand.py     ← genera PDF brandeado por sesión (segunda iteración OK)
│   └── loader.py        ← cliente XML-RPC: crea canal, secciones, slides, quizzes
├── scripts/
│   ├── test_connection.py  ← smoke test de credenciales (ya validado que funciona)
│   └── fields_get.py       ← introspección del modelo en la instancia real
├── input/               ← PDFs fuente (gitignored)
└── output/              ← previews y JSONs intermedios (gitignored)
```

## Convenciones del proyecto

- **Código, nombres de variables y comentarios: en INGLÉS.**
- **Respuestas al usuario, prompts de Claude y contenido generado: en ESPAÑOL**
  (español rioplatense neutro para el contenido de los cursos).
- Python 3.11+, type hints, sin frameworks pesados: stdlib + `anthropic` +
  `PyMuPDF` + `jsonschema` + `python-dotenv` (+ `weasyprint` o `reportlab` solo
  si se implementa pdf_brand).
- Manejo de errores: cada llamada a Claude valida el JSON contra su schema; si
  falla, 1 reintento pidiendo corrección con el error de validación en el prompt.
  Si falla de nuevo, abortar con mensaje claro (no cargar cursos a medias).
- El loader debe ser **idempotente-friendly**: antes de crear un curso, buscar si
  ya existe uno con el mismo nombre y preguntar (o flag `--force` para recrear).
  Si la carga falla a mitad de camino, hacer rollback (unlink del canal creado).
- Guardar SIEMPRE el JSON intermedio del curso en `output/<slug>.json` antes de
  cargar: permite re-cargar sin regenerar (flag `--from-json output/x.json`) y
  no gastar tokens de nuevo.
- Logs claros por consola en cada paso (extrayendo / generando sesión 2/5 /
  cargando / etc.).

## Flujo de trabajo esperado con Claude Code

1. Leer este archivo completo. ✅
2. `pip install -r requirements.txt` y copiar `.env.example` → `.env` (pedirle
   las credenciales al usuario, no inventarlas). ✅
3. Correr `scripts/test_connection.py` para confirmar acceso. ✅
4. Correr `scripts/fields_get.py` y **ajustar `loader.py`** a los campos reales. ✅
5. Completar los TODOs de `extract.py`, `generate.py`, `loader.py`, `main.py`. ✅
6. Probar end-to-end con un PDF chico contra la instancia real (curso NO
   publicado). Verificar en la UI de Odoo. ✅ (curso de prueba "Bolsines" cargado
   como borrador; branding + PDFs + portada + webapp agregados el 05/07/2026)
7. Iterar prompts con el usuario hasta que la calidad del contenido cierre.
   ← **PRÓXIMO PASO**
8. Plan primero → confirmar con el usuario → ejecutar → mostrar diffs. El usuario
   prefiere ver el plan antes de cambios grandes.

## Health check (pendiente, fase posterior)

Como la API del plan gratuito está fuera de términos, agregar más adelante un
cron (Railway) que haga authenticate + search liviano 1×/día y avise por mail si
la API empieza a rebotar, para migrar a Community con tiempo. No bloquea el MVP.

## Contexto de negocio (por si hace falta)

- GerenciAndo Canales vende esta solución a un cliente final; la instancia de
  Odoo es nueva y dedicada solo a capacitaciones (independiente de otros sistemas).
- Objetivo: minimizar trabajo manual manteniendo calidad; el paso de revisión
  humana existe justamente porque hay normativa técnica.
- Deploy futuro del pipeline: Railway (plataforma estándar del usuario), como
  servicio con endpoint o cron. El MVP es CLI local.
