# Generador de cursos eLearning con IA para Odoo

Convierte material fuente en PDF (normativas técnicas, manuales, procedimientos) en **cursos completos publicados en Odoo eLearning**: lecciones HTML con branding, quizzes de opción múltiple con feedback, y PDFs de estudio descargables — todo generado con IA y cargado automáticamente, con un paso de revisión humana antes de publicar.

**Desarrollado por/para [GerenciAndo Canales](https://gerenciandocanales.com.ar/)** (consultora de estrategia comercial e IA, Argentina) como solución para un cliente final que necesita capacitar personal sobre normativa técnica.

---

## Índice

1. [Qué hace y por qué existe](#1-qué-hace-y-por-qué-existe)
2. [Cómo funciona por dentro (arquitectura)](#2-cómo-funciona-por-dentro-arquitectura)
3. [Instalación desde cero](#3-instalación-desde-cero)
4. [Configuración (.env explicado variable por variable)](#4-configuración-env-explicado-variable-por-variable)
5. [Uso: interfaz web local](#5-uso-interfaz-web-local)
6. [Uso: línea de comandos (CLI)](#6-uso-línea-de-comandos-cli)
7. [Qué se crea exactamente en Odoo](#7-qué-se-crea-exactamente-en-odoo)
8. [Branding: lecciones y PDFs](#8-branding-lecciones-y-pdfs)
9. [Estructura del repositorio, archivo por archivo](#9-estructura-del-repositorio-archivo-por-archivo)
10. [Proveedor de IA: Claude (default) y Gemini (temporal)](#10-proveedor-de-ia-claude-default-y-gemini-temporal)
11. [Decisiones técnicas y problemas ya resueltos (leer antes de tocar código)](#11-decisiones-técnicas-y-problemas-ya-resueltos)
12. [Solución de problemas](#12-solución-de-problemas)
13. [Estado actual y pendientes](#13-estado-actual-y-pendientes)

---

## 1. Qué hace y por qué existe

### El problema

El cliente necesita convertir documentación técnica/normativa (PDFs largos y densos) en cursos de capacitación interna en su plataforma Odoo eLearning. Hacerlo a mano lleva días por curso: leer el material, estructurarlo en sesiones, redactar lecciones, armar evaluaciones, maquetar y cargar todo en Odoo.

### La solución

Este pipeline lo hace en minutos:

```
PDF(s) fuente
   │
   ▼
Extracción de texto (PyMuPDF)
   │
   ▼
IA — Pasada 1: diseña la estructura del curso (título, sesiones, temas)
   │
   ▼
IA — Pasada 2: redacta cada sesión POR SEPARADO (lección HTML + quiz)
   │
   ▼
Validación automática contra JSON schemas (reintento si falla)
   │
   ▼
JSON intermedio guardado en output/ (permite recargar sin regenerar)
   │
   ▼
Preview HTML para REVISIÓN HUMANA (lecciones + quizzes + alertas)
   │
   ▼  (solo si el humano aprueba)
Carga en Odoo vía XML-RPC (curso en borrador por defecto)
```

### El principio rector: precisión sobre todo

El material es normativa técnica donde **inventar contenido es inaceptable**. Por eso:

- **Generación en 2 pasadas, nunca todo junto**: cada sesión se genera en una llamada separada que recibe *únicamente* los fragmentos del material fuente asignados a esa sesión. El modelo escribe "con el material adelante", lo que minimiza alucinaciones.
- **Reglas duras en los prompts**: no afirmar nada que no esté en el material; citar artículo/sección de la norma cuando aplique; si el material no cubre algo, marcarlo **"(a confirmar)"** en vez de inventarlo.
- **Los puntos "(a confirmar)" se destacan en amarillo** al tope del preview: son lo primero que el revisor humano debe verificar.
- **Verificador automático de citas**: después de generar cada sesión, el pipeline extrae las citas del contenido ("según el art. 12...", "pág. 4") y las busca en el material fuente asignado. Las que no aparecen se marcan como "(a confirmar)" — el revisor pasa de "desconfiar de todo" a "revisar lo señalado".
- **Revisión humana obligatoria por defecto**: el curso se carga como NO publicado y hay una pausa de confirmación antes de cargar.

---

## 2. Cómo funciona por dentro (arquitectura)

### Decisión fundamental: programa externo, no módulo de Odoo

**No se instala nada dentro de Odoo.** El pipeline es un programa Python que corre en cualquier máquina y habla con Odoo por su API XML-RPC estándar. Ventajas: no depende de la versión de Odoo, no requiere permisos de administración del servidor, funciona igual contra Odoo Online (SaaS) o Community self-hosted. Todo lo específico de la instancia (URL, base, credenciales) vive en `.env`.

### Las dos pasadas de IA en detalle

**Pasada 1 — Estructura** (`generate_structure`): recibe TODO el material troceado en fragmentos identificados (`chunk_id`) y devuelve un JSON con:
- Título, descripción y objetivos del curso
- Lista de sesiones (la IA decide cuántas según el volumen, típicamente 3-8)
- Por cada sesión: número, título, temas, y **qué fragmentos fuente la fundamentan** (`source_chunk_ids`)

**Pasada 2 — Contenido** (`generate_session`, una llamada POR sesión): recibe la estructura general + los datos de UNA sesión + **solo los fragmentos fuente de esa sesión**, y devuelve:
- `html_content`: la lección completa en HTML con estilos inline (10-15 min de lectura)
- `quiz`: 4-6 preguntas de opción múltiple, cada una con exactamente 1 respuesta correcta y feedback explicativo por opción
- `unconfirmed_points`: lista de cosas que el material no cubría (el "escape hatch" anti-invención)

### Validación en cada paso

Cada respuesta de la IA se parsea como JSON y se valida contra su schema (`pipeline/schemas.py`) más un chequeo semántico (exactamente una respuesta correcta por pregunta). Si falla: **un** reintento pasándole los errores de validación al modelo. Si falla de nuevo: aborta con error claro. **Nunca se cargan cursos a medias.**

### Carga transaccional en Odoo

El loader es defensivo:
- Antes de crear, busca si ya existe un curso con el mismo nombre → se niega salvo `--force` (que borra el viejo primero).
- Si cualquier cosa falla a mitad de la carga → **rollback automático**: borra el canal creado (el borrado cascadea a slides, preguntas y respuestas).

---

## 3. Instalación desde cero

### Requisitos previos

- **Python 3.11 o superior** ([python.org](https://www.python.org/downloads/); en Windows marcar "Add Python to PATH" al instalar)
- Una **instancia de Odoo** con la app **eLearning** (`website_slides`) instalada
- Una **API key de IA**: Anthropic (producción) o Google Gemini (desarrollo, tiene tier gratuito)

### Pasos

```bash
# 1. Clonar el repo
git clone https://github.com/bruscofacundo1/cursosia.git
cd cursosia

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Crear el archivo de credenciales
cp .env.example .env        # en Windows: copy .env.example .env
#    ...y completarlo (ver sección 4)

# 4. Verificar la conexión con Odoo
python scripts/test_connection.py
#    Debe mostrar: authenticate ✓, read ✓, create ✓, unlink ✓

# 5. Listo. Probar con un PDF:
python main.py input/mi_material.pdf --dry-run
```

> **Si es una instancia de Odoo NUEVA** (distinta a la ya configurada): correr también `python scripts/fields_get.py`, que introspecciona el modelo de datos real y guarda el resultado en `scripts/fields_output.json`. Comparar con los campos que usa `pipeline/loader.py` por si la versión de Odoo cambió algo. Contra saas-19.3 ya está verificado.

---

## 4. Configuración (.env explicado variable por variable)

> ⚠️ **Setup casi plug-and-play:** el `.env.example` ya trae las credenciales reales de la **instancia Odoo de prueba** (funcionan tal cual). Lo ÚNICO que tenés que conseguir es tu propia key de Gemini — es gratis y tarda 10 segundos en [AI Studio](https://aistudio.google.com/apikey). ¿Por qué no viene incluida? Lo intentamos: Google escanea los repos públicos y **revocó la key en menos de una hora**. Cualquier key de Gemini publicada muere sola; la de Odoo no tiene ese mecanismo y por eso sí puede venir en el repo.
>
> ```bash
> cp .env.example .env      # Windows: copy .env.example .env
> # abrir .env y pegar tu key en GEMINI_API_KEY=
> ```

El archivo `.env` contiene:

```ini
# ── Odoo ──────────────────────────────────────────────
ODOO_URL=https://tubase.odoo.com    # URL de la instancia, SIN barra final
ODOO_DB=tubase                       # nombre de la base de datos (en Odoo Online
                                     # suele ser igual al subdominio)
ODOO_USER=usuario@email.com          # email del usuario de Odoo con permisos de
                                     # administración de eLearning
ODOO_API_KEY=xxxxxxxxxxxx            # API key del usuario. Se genera en Odoo:
                                     # Ajustes → Usuarios → (tu usuario) →
                                     # Seguridad de la cuenta → Claves API → Nueva

# ── IA: Anthropic (proveedor por defecto) ─────────────
ANTHROPIC_API_KEY=sk-ant-...         # de https://console.anthropic.com
# CLAUDE_MODEL=claude-sonnet-4-6     # opcional, override del modelo

# ── IA: Gemini (fallback TEMPORAL de desarrollo) ──────
# Con LLM_PROVIDER=gemini el pipeline usa la API de Gemini en vez de Claude
# (mismos prompts, schemas y validación; solo cambia el transporte).
# Para volver a Claude: comentar LLM_PROVIDER.
LLM_PROVIDER=gemini
GEMINI_API_KEY=...                   # de https://aistudio.google.com/apikey
# GEMINI_MODEL=gemini-2.5-flash      # opcional, override del modelo
```

---

## 5. Uso: interfaz web local

Para quien prefiere no usar la terminal:

```bash
python webapp.py
```

y abrir **http://localhost:8000** en el navegador. El flujo:

1. **Formulario**: subir PDF(s) fuente + título tentativo (opcional) + imagen de portada del curso (opcional)
2. **Progreso en vivo**: la página se actualiza sola mostrando los logs (extrayendo, generando sesión 2/4, etc.)
3. **Revisión**: preview completo embebido (lecciones como van a quedar, quizzes con las respuestas correctas en verde, puntos "(a confirmar)" destacados) + opciones de carga: subir **material complementario** (PDFs extra que van como sección final descargable), incluir el/los PDF(s) fuente originales (marcado por defecto), *publicar directo* (si no, queda borrador) y *reemplazar si ya existe*
4. **Carga**: botón "Cargar en Odoo" → al terminar da el link directo al backend de eLearning

⚠️ Es una herramienta **local y mono-usuario** (un curso a la vez, sin login). Es también el molde del futuro servicio en Railway: la versión cloud le pondrá autenticación al mismo flujo.

---

## 6. Uso: línea de comandos (CLI)

```bash
# Flujo completo: extrae, genera, guarda JSON, muestra preview, pregunta, carga
python main.py input/normativa.pdf --titulo "Seguridad Eléctrica"

# Varios PDFs → un solo curso
python main.py input/parte1.pdf input/parte2.pdf --titulo "Curso X"

# Generar y ver el preview SIN tocar Odoo
python main.py input/normativa.pdf --dry-run

# Recargar un curso ya generado (NO regenera, no gasta tokens de IA)
python main.py --from-json output/seguridad_eléctrica.json

# Reemplazar un curso existente, con portada, publicado directo
python main.py --from-json output/x.json --force --portada input/foto.png --publicar
```

| Flag | Efecto |
|---|---|
| `--titulo "X"` | Sugerencia de título para la IA (opcional; si falta, decide ella) |
| `--dry-run` | Genera + preview, **no toca Odoo** |
| `--from-json ruta.json` | Carga un JSON ya generado. Si el JSON está incompleto (generación interrumpida), **reanuda automáticamente** desde la última sesión completada |
| `--portada imagen.png` | Imagen de tarjeta del curso en el catálogo (PNG/JPG) |
| `--publicar` | Publica el curso al cargarlo (default: queda **borrador**) |
| `--force` | Si existe un curso con el mismo nombre, lo borra y recrea |
| `--no-pdf` | No genera los PDFs de estudio descargables |
| `--adjuntos a.pdf b.pdf` | PDFs extra cargados como sección final "Material complementario" (ej.: la normativa original completa) |
| `--skip-review` | Salta la pausa de confirmación humana (usar con criterio) |

**El JSON intermedio es oro**: cada generación guarda `output/<slug>.json` con el curso completo. Regenerar cuesta tokens y da resultados distintos; recargar desde JSON es gratis y reproducible.

El JSON además: se **checkpointea después de cada sesión** (una falla a mitad de camino pierde como máximo una sesión — se reanuda con `--from-json` o el botón "Reanudar" de la webapp), guarda los **fragmentos fuente** (para reanudar sin los PDFs) y un bloque **`metadata`** con proveedor, modelo y fecha de generación (trazabilidad para iterar prompts).

### Scripts auxiliares

```bash
python scripts/test_connection.py   # ¿la API de Odoo responde? (authenticate/read/create/unlink)
python scripts/fields_get.py        # introspección del modelo de datos de la instancia
```

---

## 7. Qué se crea exactamente en Odoo

Por cada curso, vía XML-RPC contra estos modelos de `website_slides`:

| Modelo Odoo | Qué es | Qué crea el pipeline |
|---|---|---|
| `slide.channel` | El curso | 1 registro: título, descripción HTML con objetivos, `channel_type='training'`, `enroll='invite'`, borrador salvo `--publicar`, portada opcional (`image_1920`), **tags de catálogo** (`tag_ids`, generados por la IA, grupo "Temas") |
| `slide.slide` con `is_category=True` | Separador de sección | 1 por sesión: "Sesión N: Título" |
| `slide.slide` categoría `article` | La lección | 1 por sesión: HTML brandeado en `html_content` + duración estimada (`completion_time`). El quiz completo se crea **anidado en la misma llamada** (comandos one2many): 1 RPC por lección en vez de ~25 |
| `slide.slide` categoría `document` | Material de estudio | 1 por sesión: PDF brandeado en `binary_content` (base64), descargable |
| `slide.slide` categoría `document` | Material complementario | Opcional: PDFs extra del usuario (y/o los PDFs fuente originales) en una sección final |
| `slide.question` | Pregunta de quiz | 4-6 por sesión, **colgadas directamente del slide artículo** (Odoo muestra el quiz al final de la lección; verificado en saas-19.3, no hace falta slide separado) |
| `slide.answer` | Opción de respuesta | 3-5 por pregunta: texto, `is_correct`, `comment` (feedback que ve el participante) |

El orden lo da el campo `sequence`: sección → artículo → documento, por cada sesión.

---

## 8. Branding: lecciones y PDFs

La marca está **fija en el código** (decisión deliberada: no es configurable por corrida; si se necesita una plantilla para otro cliente se hace como cambio puntual). Todo vive en `pipeline/branding.py`:

```python
BRAND = {
    "COLOR_PRIMARY": "#9B55A7",     # violeta del wordmark GerenciAndo
    "COLOR_SECONDARY": "#402343",   # ciruela oscuro de "Canales"
    "COLOR_ACCENT": "#6D2998",      # violeta profundo del degradado del isotipo
    "LOGO_PATH": "assets/logo.png",
    "COMPANY_NAME": "Gerenciando Canales - Consultora",
    "WEBSITE_URL": "https://gerenciandocanales.com.ar/",
    "FONT_STACK": "Roboto, 'Helvetica Neue', Arial, Helvetica, sans-serif",
}
```

(La paleta fue extraída por muestreo de píxeles del logo real.)

**Lecciones HTML** (`apply_branding`): cada lección se envuelve en una plantilla con logo arriba a la derecha, título con barra violeta, y footer con empresa + web. La IA genera el contenido con placeholders `{{COLOR_PRIMARY}}` etc. que se sustituyen al cargar. El logo va **embebido como data URI base64** (~27 KB) — ver por qué en la sección 11.

**PDFs de estudio** (`pipeline/pdf_brand.py`): plantilla A4 fija donde solo cambia el contenido:
- Header en cada página: logo arriba a la derecha
- Footer en cada página: web abajo a la izquierda, "Página N de M" abajo a la derecha
- Tipografía Roboto real embebida (los .ttf están en `assets/fonts/`)
- Renderizado con `xhtml2pdf` (HTML → PDF en Python puro)

---

## 9. Estructura del repositorio, archivo por archivo

```
cursosia/
├── CLAUDE.md            Contexto para Claude Code (el asistente de IA con que se
│                        desarrolló esto): decisiones de arquitectura, convenciones.
│                        Leerlo también como humano: es la memoria del proyecto.
├── README.md            Este archivo.
├── .env.example         Plantilla de credenciales. Copiar a .env y completar.
├── .gitignore           Excluye .env, input/, output/, caches.
├── requirements.txt     Dependencias Python.
├── main.py              CLI orquestador: parsea flags y encadena el pipeline.
├── webapp.py            Interfaz web local (Flask, puerto 8000).
│
├── pipeline/            El corazón:
│   ├── extract.py       PDF → lista de fragmentos de texto con ID (PyMuPDF).
│   │                    Trocea de a 3 páginas. Detecta PDFs escaneados y avisa.
│   ├── generate.py      Llamadas a la IA (pasada 1 y 2) + validación + reintento.
│   │                    Acá vive el switch Claude/Gemini (LLM_PROVIDER).
│   ├── prompts.py       Los system prompts en español de ambas pasadas. Las
│   │                    REGLAS DE FIDELIDAD son el mecanismo anti-alucinación:
│   │                    iterar la redacción, no quitar las reglas.
│   ├── schemas.py       JSON schemas que DEBEN cumplir las salidas de la IA +
│   │                    chequeo de exactamente-una-correcta por pregunta.
│   ├── branding.py      Paleta, logo (data URI), plantilla HTML de lección.
│   ├── pdf_brand.py     Generador del PDF brandeado por sesión (xhtml2pdf).
│   ├── preview.py       Genera el HTML único de revisión humana.
│   └── loader.py        Cliente XML-RPC: crea curso, secciones, slides, quizzes.
│                        Idempotente (busca duplicados) y con rollback.
│
├── scripts/
│   ├── test_connection.py   Smoke test de la API de Odoo.
│   └── fields_get.py        Introspección del modelo de datos real.
│
├── assets/
│   ├── logo.png             Logo master en alta resolución (5400px).
│   └── fonts/               Roboto Regular/Bold/Italic (.ttf) para los PDFs.
│
├── input/               PDFs fuente (contenido gitignored).
├── output/              JSONs generados + previews (contenido gitignored).
└── .claude/launch.json  Config para levantar webapp desde Claude Code.
```

**Convenciones del código**: código/variables/comentarios en inglés; mensajes al usuario, prompts y contenido generado en español. Python 3.11+, type hints, sin frameworks pesados.

---

## 10. Proveedor de IA: Claude (default) y Gemini (temporal)

La decisión de producción es **API de Claude (Anthropic)**, modelo `claude-sonnet-4-6`. Mientras no hubo key de Anthropic se agregó un **fallback temporal a Gemini** (que tiene tier gratuito):

- `LLM_PROVIDER=gemini` en `.env` → usa la API de Gemini (`gemini-2.5-flash` por defecto)
- Los prompts, schemas, validación y reintentos son **idénticos** para ambos; solo cambia el transporte (para Gemini se usa la API REST con la stdlib, sin dependencias nuevas, y se pide salida JSON nativa con `responseMimeType`)
- **Volver a Claude** = comentar `LLM_PROVIDER` y setear `ANTHROPIC_API_KEY`. Nada más.

⚠️ Los prompts de fidelidad fueron redactados pensando en Claude. Con Gemini la validación de formato protege igual, pero la calidad del grounding puede variar: el paso de revisión humana es aún más importante. Para contenido que va al cliente final, regenerar con Claude.

---

## 11. Decisiones técnicas y problemas ya resueltos

**Leer esta sección antes de tocar el código.** Cada punto costó debugging real contra la instancia:

1. **`create` por XML-RPC devuelve una LISTA.** Cuando se le pasa una lista de diccionarios (aunque tenga uno solo), Odoo devuelve una lista de IDs. Usar ese valor directo como `channel_id` revienta en el servidor con `TypeError: unhashable type: 'list'`. El wrapper `OdooClient.create` en `loader.py` desempaqueta con `[0]` — no lo quites.

2. **`channel_type` es obligatorio** en `slide.channel` (saas-19.3): selección `training`/`documentation`. El loader manda `training`.

3. **`enroll` en el plan One App Free solo acepta `public`/`invite`** (no existe `payment`).

4. **`description` del curso es un campo HTML**: los `\n` de texto plano colapsan. El loader arma la descripción como HTML real.

5. **El logo de las lecciones va como data URI, no como URL.** Odoo SaaS sirve un *placeholder* a usuarios no logueados cuando el `<img>` apunta a un `ir.attachment` suelto — incluso con `public=True` y hasta con `access_token` (verificado empíricamente). En cambio, el sanitizador HTML de Odoo **conserva** los `data:image/png;base64,...` (también verificado). Por eso `branding.py` embebe el logo reescalado a 480px (~27 KB) directamente en el HTML de cada lección.

6. **El quiz vive DENTRO del slide artículo.** `slide.question.slide_id` puede apuntar a un slide de categoría `article` y Odoo muestra el quiz al final de la lección. No hace falta (ni conviene) un slide separado de categoría `quiz`. Verificado en saas-19.3.

7. **xhtml2pdf en Windows necesita un parche.** Al cargar fuentes TTF las copia a un archivo temporal que mantiene abierto, y reportlab no puede reabrirlo (`PermissionError`). `pdf_brand.py` lo resuelve con `pisaFileObject.getNamedFile = lambda self: self.uri` (usa el archivo original). Sin eso, los PDFs no se generan en Windows.

8. **Consolas Windows y Unicode**: cmd/PowerShell suelen usar cp1252, que no puede imprimir `✓`/`⚠` y crashea Python. `main.py`, `webapp.py` y los scripts reconfiguran stdout a UTF-8 automáticamente.

9. **Riesgo conocido de la instancia**: es Odoo Online plan gratuito "One App Free" (saas-19.3), donde la API XML-RPC funciona (validado 04/07/2026) **pero no está oficialmente incluida** — Odoo podría cerrarla sin aviso. Decisión tomada: aceptar el riesgo en desarrollo; para producción se evaluará seguir ahí o migrar a Odoo Community self-hosted (donde la API está garantizada). El código es agnóstico: mismo `.env`, misma lógica.

10. **La sesión title-dedup**: los modelos tienden a repetir el título de la sesión al inicio del `html_content` aunque la plantilla ya lo muestra. `strip_leading_title()` en `branding.py` lo elimina, y el prompt lo prohíbe explícitamente.

---

## 12. Solución de problemas

| Síntoma | Causa probable / solución |
|---|---|
| `Authentication failed — check .env` | Credenciales mal en `.env`. Verificar que `ODOO_DB` sea el nombre de la base (no la URL) y que la API key sea de ese usuario. Correr `python scripts/test_connection.py`. |
| `KeyError: 'ODOO_URL'` | No existe `.env` o está en otra carpeta. Copiar `.env.example` → `.env` en la raíz del repo. |
| `LLM_PROVIDER=gemini but GEMINI_API_KEY is not set` | Falta la key de Gemini en `.env`. |
| La IA devuelve error de validación dos veces y aborta | Material fuente muy raro o modelo con mal día. Reintentar; si persiste, revisar el texto extraído (¿el PDF es escaneado?). |
| `X page(s) with no extractable text (scanned PDF?)` | El PDF es imagen escaneada. OCR no está implementado (fuera del MVP); conseguir el PDF con texto real. |
| `A course named 'X' already exists` | Ya hay un curso con ese nombre en Odoo. Usar `--force` para reemplazarlo o cambiar el título. |
| PDF de sesión falla con `PermissionError ... .ttf` (Windows) | El monkeypatch de xhtml2pdf (sección 11.7) fue removido. Restaurarlo. |
| `UnicodeEncodeError ... charmap` | Falta el reconfigure de UTF-8 al inicio del script (sección 11.8). |
| La API de Odoo dejó de responder de un día para otro | Puede ser el cierre del plan gratuito (sección 11.9). Verificar con `test_connection.py`; si rebota consistentemente, migrar a Community self-hosted. |
| La generación con IA falla de golpe (antes andaba) con error de autenticación/permiso | **Probable: Google revocó la key de Gemini.** Como el `.env` de prueba está público en este repo, Google puede detectar la key filtrada y deshabilitarla automáticamente en cualquier momento. Verificar en [AI Studio](https://aistudio.google.com/apikey); si está revocada, generar una nueva y reemplazarla en el `.env`. Lo mismo aplica a la key de Odoo si alguien la rotó. |

---

## 13. Estado actual y pendientes

### Funcionando (probado end-to-end contra la instancia real)

- ✅ Extracción, generación 2 pasadas, validación con reintento, JSON intermedio
- ✅ Preview de revisión humana con alertas "(a confirmar)"
- ✅ Carga completa en Odoo: curso + secciones + lecciones + quizzes + PDFs, con rollback
- ✅ Branding GerenciAndo completo (lecciones y PDFs) con paleta extraída del logo real
- ✅ Portada de curso (`--portada` / formulario web)
- ✅ Interfaz web local (`webapp.py`)
- ✅ Fallback Gemini operativo (es lo que está activo ahora)

### Pendiente

- ⬜ **Key de Anthropic** → volver a Claude para producción (2 líneas del `.env`)
- ⬜ **Iteración de calidad** de prompts con material real del cliente y feedback humano
- ⬜ **OCR** para PDFs escaneados (fuera del MVP)
- ⬜ **Health check diario** de la API de Odoo (cron en Railway que haga authenticate + search y avise por mail si rebota, para migrar con tiempo)
- ⬜ **Deploy en Railway** como servicio web (webapp.py es el molde; falta autenticación y multi-trabajo)
- ⬜ Branding de la plataforma Odoo en sí (logo del sitio, theme) — se hace una vez a mano en el editor web de Odoo

---

*Proyecto desarrollado con [Claude Code](https://claude.com/claude-code). El archivo `CLAUDE.md` contiene el contexto de trabajo para el asistente; mantenerlo actualizado si se toman decisiones nuevas.*
