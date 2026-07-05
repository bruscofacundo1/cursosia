"""Progress report: course attendance and quiz stats straight from Odoo.

Closes the loop after publishing: who enrolled, who finished, which lessons
get stuck, how many quiz attempts each lesson takes. Run it any time:

  python scripts/reporte_avance.py            # all courses
  python scripts/reporte_avance.py --curso 10 # one course (channel id)
"""

import argparse
import os
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

url = os.environ["ODOO_URL"].rstrip("/")
db = os.environ["ODOO_DB"]
user = os.environ["ODOO_USER"]
key = os.environ["ODOO_API_KEY"]

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, user, key, {})
if not uid:
    raise SystemExit("Authentication failed — check .env")
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")


def call(model, method, *args, **kw):
    return models.execute_kw(db, uid, key, model, method, list(args), kw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reporte de avance de cursos eLearning.")
    parser.add_argument("--curso", type=int, help="Channel id de un curso puntual (default: todos)")
    args = parser.parse_args()

    domain = [["id", "=", args.curso]] if args.curso else []
    channels = call(
        "slide.channel", "search_read", domain,
        fields=["name", "is_published", "members_count", "members_completed_count",
                "members_engaged_count", "total_views"],
        order="id",
    )
    if not channels:
        print("No hay cursos." if not args.curso else f"No existe el curso {args.curso}.")
        return 0

    for ch in channels:
        estado = "PUBLICADO" if ch["is_published"] else "borrador"
        print(f"\n═══ [{ch['id']}] {ch['name']} ({estado}) ═══")
        inscriptos = ch["members_count"]
        print(f"  Inscriptos: {inscriptos} | Completaron: {ch['members_completed_count']} | "
              f"En curso: {ch['members_engaged_count']} | Vistas totales: {ch['total_views']}")
        if not inscriptos:
            print("  (sin participantes todavía — no hay métricas de avance)")
            continue

        pct = round(100 * ch["members_completed_count"] / inscriptos)
        print(f"  Tasa de finalización: {pct}%")

        # Per-lesson progress: slide.slide.partner tracks each attendee×slide.
        slides = call(
            "slide.slide", "search_read",
            [["channel_id", "=", ch["id"]], ["is_category", "=", False]],
            fields=["name", "slide_category", "question_ids"], order="sequence",
        )
        print(f"  {'Lección':52} {'Completaron':>11} {'Quiz: intentos prom.':>20}")
        for sl in slides:
            partners = call(
                "slide.slide.partner", "search_read",
                [["slide_id", "=", sl["id"]]],
                fields=["completed", "quiz_attempts_count"],
            )
            done = sum(1 for p in partners if p.get("completed"))
            attempts = [p.get("quiz_attempts_count") or 0 for p in partners if sl["question_ids"]]
            avg = f"{sum(attempts) / len(attempts):.1f}" if attempts else "-"
            flag = " ⚠️" if inscriptos and done / inscriptos < 0.5 else ""
            print(f"  {sl['name'][:52]:52} {done:>8}/{inscriptos:<3} {avg:>18}{flag}")

        print("  (⚠️ = menos de la mitad de los inscriptos completó esa lección: posible cuello de botella)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
