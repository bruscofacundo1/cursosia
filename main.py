"""CLI orchestrator: PDF(s) → Claude → preview → Odoo.

Usage:
  python main.py input/normativa.pdf --titulo "Seguridad Eléctrica"
  python main.py input/a.pdf input/b.pdf --titulo "Curso X" --publicar
  python main.py --from-json output/curso_x.json            # re-load without regenerating
  python main.py input/x.pdf --skip-review --publicar       # fully automated (careful!)
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows consoles often default to cp1252, which can't print ✓/⚠ and crashes.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

load_dotenv()

from pipeline.extract import extract_chunks          # noqa: E402
from pipeline.generate import generate_course        # noqa: E402
from pipeline.loader import load_course               # noqa: E402
from pipeline.preview import write_preview            # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "output"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an Odoo eLearning course from source PDFs using Claude.")
    parser.add_argument("pdfs", nargs="*", type=Path, help="Source PDF file(s)")
    parser.add_argument("--titulo", help="Tentative course title (hint for Claude)")
    parser.add_argument("--from-json", type=Path, help="Load a previously generated course JSON (skip generation)")
    parser.add_argument("--publicar", action="store_true", help="Publish the course immediately (default: draft)")
    parser.add_argument("--skip-review", action="store_true", help="Skip the human-review pause")
    parser.add_argument("--force", action="store_true", help="Replace an existing course with the same name")
    parser.add_argument("--no-pdf", action="store_true", help="Skip the branded per-session PDF slides")
    parser.add_argument("--portada", type=Path, help="Image file for the course card picture (PNG/JPG)")
    parser.add_argument("--dry-run", action="store_true", help="Generate + preview only, do not touch Odoo")
    args = parser.parse_args()

    if args.from_json:
        course = json.loads(args.from_json.read_text(encoding="utf-8"))
        print(f"✓ Loaded course JSON from {args.from_json}")
    else:
        if not args.pdfs:
            parser.error("Provide at least one PDF (or --from-json).")
        for p in args.pdfs:
            if not p.exists():
                parser.error(f"File not found: {p}")

        chunks = extract_chunks(args.pdfs)
        course = generate_course(chunks, title_hint=args.titulo)

        OUTPUT_DIR.mkdir(exist_ok=True)
        slug = "".join(c if c.isalnum() else "_" for c in course["structure"]["title"].lower())[:60]
        json_path = OUTPUT_DIR / f"{slug}.json"
        json_path.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ Course JSON saved: {json_path} (re-load later with --from-json)")

    preview_path = write_preview(course, OUTPUT_DIR)

    if args.dry_run:
        print("Dry run: stopping before Odoo load.")
        return 0

    if not args.skip_review:
        print(f"\n→ Revisá el preview: {preview_path}")
        answer = input("¿Cargar el curso en Odoo? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado. El JSON quedó guardado; podés recargar con --from-json.")
            return 0

    if args.portada and not args.portada.exists():
        parser.error(f"Cover image not found: {args.portada}")

    load_course(
        course,
        publish=args.publicar,
        force=args.force,
        with_pdf=not args.no_pdf,
        cover_image=str(args.portada) if args.portada else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
