"""Minimal local web UI for the course pipeline.

Same pipeline as main.py, wrapped in a browser flow so a human can try it
without the terminal: upload PDF(s) → watch generation progress → review the
preview → load into Odoo (draft) with one button.

Single-job by design (one course at a time); this is a local testing tool and
the blueprint for the future Railway service, not a multi-user server.

  python webapp.py   →  http://localhost:8000
"""

import contextlib
import io
import json
import sys
import threading
import traceback
from pathlib import Path

from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

from flask import Flask, redirect, render_template_string, request  # noqa: E402

from pipeline.extract import extract_chunks  # noqa: E402
from pipeline.generate import generate_course  # noqa: E402
from pipeline.loader import load_course  # noqa: E402
from pipeline.preview import write_preview  # noqa: E402

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
PORT = 8000

app = Flask(__name__)

# One job at a time; reset via the "Nuevo curso" button.
JOB: dict = {"state": "idle"}  # idle | running | review | loading | loaded | error


def _fresh_job() -> dict:
    return {
        "state": "idle", "log": [], "error": None,
        "title": None, "json_path": None, "preview_path": None,
        "cover_path": None, "channel_id": None,
        "source_pdfs": [], "extra_docs": [],
    }


JOB = _fresh_job()


class _LogWriter(io.TextIOBase):
    """Captures the pipeline's print() output into the job log."""

    def write(self, s: str) -> int:
        s = s.strip()
        if s:
            JOB["log"].append(s)
        return len(s)


def _run_generation(pdf_paths: list[Path], title_hint: str | None) -> None:
    try:
        # redirect_stdout is process-wide, acceptable: single-job local tool.
        with contextlib.redirect_stdout(_LogWriter()):
            chunks = extract_chunks(pdf_paths)
            course = generate_course(chunks, title_hint=title_hint)

            OUTPUT_DIR.mkdir(exist_ok=True)
            title = course["structure"]["title"]
            slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:60]
            json_path = OUTPUT_DIR / f"{slug}.json"
            json_path.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")

            preview_path = write_preview(course, OUTPUT_DIR)

        JOB.update(state="review", title=title, json_path=str(json_path), preview_path=str(preview_path))
    except Exception as exc:  # noqa: BLE001
        JOB.update(state="error", error=f"{exc}\n\n{traceback.format_exc()}")


def _run_load(publish: bool, force: bool) -> None:
    try:
        course = json.loads(Path(JOB["json_path"]).read_text(encoding="utf-8"))
        with contextlib.redirect_stdout(_LogWriter()):
            channel_id = load_course(
                course, publish=publish, force=force,
                cover_image=JOB["cover_path"],
                extra_docs=JOB["extra_docs"] or None,
            )
        JOB.update(state="loaded", channel_id=channel_id)
    except Exception as exc:  # noqa: BLE001
        JOB.update(state="error", error=f"{exc}\n\n{traceback.format_exc()}")


_PAGE = """
<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Generador de cursos — GerenciAndo Canales</title>
{refresh}
<style>
  body {{ font-family: Roboto, Arial, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; color: #222; background: #ffffff; color-scheme: light; }}
  h1 {{ color: #402343; }} h1 span {{ color: #9B55A7; }}
  .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 20px 24px; margin: 16px 0; }}
  label {{ display: block; margin: 12px 0 4px; font-weight: bold; color: #402343; }}
  input[type=text] {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 6px; }}
  .btn {{ background: #9B55A7; color: white; border: none; padding: 10px 22px; border-radius: 6px;
         font-size: 15px; cursor: pointer; text-decoration: none; display: inline-block; margin-top: 14px; }}
  .btn.gray {{ background: #888; }}
  .log {{ background: #1e1e1e; color: #d6c2e0; font-family: Consolas, monospace; font-size: 13px;
         padding: 14px; border-radius: 8px; white-space: pre-wrap; max-height: 380px; overflow-y: auto; }}
  .err {{ background: #fdecea; border: 1px solid #f5c6cb; color: #721c24; padding: 12px; border-radius: 8px; white-space: pre-wrap; font-size: 13px; }}
  .ok {{ background: #e8f5e9; border: 1px solid #a5d6a7; padding: 12px; border-radius: 8px; }}
  iframe {{ width: 100%; height: 520px; border: 1px solid #ddd; border-radius: 8px; }}
  small {{ color: #888; }}
</style></head><body>
<h1>Generador de cursos <span>eLearning + IA</span></h1>
{body}
</body></html>
"""


def _render(body: str, auto_refresh: bool = False) -> str:
    refresh = '<meta http-equiv="refresh" content="3">' if auto_refresh else ""
    return _PAGE.format(body=body, refresh=refresh)


@app.get("/")
def index():
    state = JOB["state"]

    if state == "idle":
        return _render("""
<div class="card"><form action="/generar" method="post" enctype="multipart/form-data">
  <label>PDF(s) fuente *</label>
  <input type="file" name="pdfs" accept=".pdf" multiple required>
  <label>Título tentativo <small>(opcional, la IA decide si lo dejás vacío)</small></label>
  <input type="text" name="titulo" placeholder="Ej: Seguridad Eléctrica">
  <label>Imagen de portada del curso <small>(opcional, PNG/JPG)</small></label>
  <input type="file" name="portada" accept="image/png,image/jpeg">
  <button class="btn" type="submit">Generar curso</button>
  <p><small>La generación tarda unos minutos según el tamaño del material.</small></p>
</form></div>""")

    log_html = "<div class='log'>" + "\n".join(JOB["log"][-40:]) + "</div>"

    if state in ("running", "loading"):
        msg = "Generando el curso con IA..." if state == "running" else "Cargando en Odoo..."
        return _render(f"<div class='card'><b>⏳ {msg}</b> <small>(esta página se actualiza sola)</small>{log_html}</div>", auto_refresh=True)

    if state == "error":
        return _render(f"""
<div class="err"><b>Falló:</b>\n{JOB['error']}</div>{log_html}
<form action="/reset" method="post"><button class="btn gray">Volver a empezar</button></form>""")

    if state == "review":
        return _render(f"""
<div class="card">
  <h3>✓ Curso generado: {JOB['title']}</h3>
  <p>Revisá el contenido abajo (lecciones, quizzes y puntos "(a confirmar)"). Si está bien, cargalo en Odoo.</p>
  <form action="/cargar" method="post" enctype="multipart/form-data">
    <label>Material complementario <small>(opcional, PDFs — van como sección final descargable)</small></label>
    <input type="file" name="adjuntos" accept=".pdf" multiple>
    <label><input type="checkbox" name="incluir_fuente" checked> Incluir el/los PDF(s) fuente originales como material complementario</label>
    <label><input type="checkbox" name="publicar"> Publicar directo (si no, queda borrador)</label>
    <label><input type="checkbox" name="force"> Reemplazar si ya existe un curso con el mismo nombre</label>
    <button class="btn" type="submit">Cargar en Odoo</button>
  </form>
  <form action="/reset" method="post" style="margin-top:8px">
    <button class="btn gray" type="submit">Descartar</button>
  </form>
</div>
<iframe src="/preview"></iframe>
{log_html}""")

    if state == "loaded":
        import os
        backend = os.environ["ODOO_URL"].rstrip("/") + "/odoo/action-website_slides.slide_channel_action_overview"
        return _render(f"""
<div class="ok"><b>✓ Curso cargado en Odoo</b> (canal id {JOB['channel_id']}).<br>
<a href="{backend}" target="_blank">Abrir el backend de eLearning →</a></div>
<form action="/reset" method="post"><button class="btn">Nuevo curso</button></form>
{log_html}""")

    return _render("<div class='err'>Estado desconocido.</div>")


@app.post("/generar")
def generar():
    global JOB
    if JOB["state"] == "running":
        return redirect("/")
    JOB = _fresh_job()

    files = [f for f in request.files.getlist("pdfs") if f.filename]
    if not files:
        JOB.update(state="error", error="No se subió ningún PDF.")
        return redirect("/")

    INPUT_DIR.mkdir(exist_ok=True)
    pdf_paths = []
    for f in files:
        dest = INPUT_DIR / Path(f.filename).name
        f.save(dest)
        pdf_paths.append(dest)
    JOB["source_pdfs"] = [str(p) for p in pdf_paths]

    cover = request.files.get("portada")
    if cover and cover.filename:
        cover_dest = INPUT_DIR / Path(cover.filename).name
        cover.save(cover_dest)
        JOB["cover_path"] = str(cover_dest)

    title_hint = request.form.get("titulo", "").strip() or None
    JOB["state"] = "running"
    threading.Thread(target=_run_generation, args=(pdf_paths, title_hint), daemon=True).start()
    return redirect("/")


@app.get("/preview")
def preview():
    if not JOB.get("preview_path"):
        return "No hay preview todavía.", 404
    return Path(JOB["preview_path"]).read_text(encoding="utf-8")


@app.post("/cargar")
def cargar():
    if JOB["state"] != "review":
        return redirect("/")

    # Complementary material: uploaded PDFs + optionally the source PDFs.
    extra_docs: list[str] = []
    for f in request.files.getlist("adjuntos"):
        if f.filename and f.filename.lower().endswith(".pdf"):
            dest = INPUT_DIR / Path(f.filename).name
            f.save(dest)
            extra_docs.append(str(dest))
    if request.form.get("incluir_fuente"):
        extra_docs = JOB["source_pdfs"] + extra_docs
    JOB["extra_docs"] = extra_docs

    JOB["state"] = "loading"
    publish = bool(request.form.get("publicar"))
    force = bool(request.form.get("force"))
    threading.Thread(target=_run_load, args=(publish, force), daemon=True).start()
    return redirect("/")


@app.post("/reset")
def reset():
    global JOB
    JOB = _fresh_job()
    return redirect("/")


if __name__ == "__main__":
    print(f"→ Abrí http://localhost:{PORT} en el navegador")
    app.run(host="127.0.0.1", port=PORT, debug=False)
