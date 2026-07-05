"""Human-review preview: one self-contained HTML file with the whole course.

Shown BEFORE loading/publishing. Includes lessons (branded, as they will look),
quizzes with correct answers highlighted, and every '(a confirmar)' flag in a
warning box at the top — those are the points the reviewer must check first.
"""

import html
from pathlib import Path

from .branding import BRAND, apply_branding


def write_preview(course: dict, out_dir: Path) -> Path:
    structure = course["structure"]
    title = structure["title"]
    slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:60]
    out = out_dir / f"preview_{slug}.html"

    parts = [
        f"<h1 style='font-family:Arial;color:{BRAND['COLOR_SECONDARY']}'>PREVIEW — {html.escape(title)}</h1>",
        f"<p style='font-family:Arial'>{html.escape(structure['description'])}</p>",
    ]

    flags = [
        (s["session_number"], p)
        for s in course["sessions"]
        for p in s.get("unconfirmed_points", [])
    ]
    if flags:
        items = "".join(f"<li>Sesión {n}: {html.escape(p)}</li>" for n, p in flags)
        parts.append(
            "<div style='font-family:Arial;background:#fff3cd;border:1px solid #ffc107;"
            "padding:12px 16px;border-radius:6px'><b>⚠️ Puntos a confirmar antes de publicar "
            f"({len(flags)}):</b><ul>{items}</ul></div>"
        )

    for s in course["sessions"]:
        n = s["session_number"]
        parts.append("<hr style='margin:40px 0'/>")
        parts.append(
            apply_branding(
                s["html_content"],
                course_title=title,
                session_title=s["title"],
                session_number=n,
            )
        )
        quiz_html = [f"<h3 style='font-family:Arial;color:{BRAND['COLOR_PRIMARY']}'>Quiz — Sesión {n}</h3><ol style='font-family:Arial'>"]
        for q in s["quiz"]:
            answers = "".join(
                f"<li style='{'color:green;font-weight:bold' if a['is_correct'] else ''}'>"
                f"{html.escape(a['text'])}"
                + (f" <i style='color:#888;font-weight:normal'>— {html.escape(a.get('feedback',''))}</i>" if a.get("feedback") else "")
                + "</li>"
                for a in q["answers"]
            )
            quiz_html.append(f"<li><b>{html.escape(q['question'])}</b><ul>{answers}</ul></li>")
        quiz_html.append("</ol>")
        parts.append("".join(quiz_html))

    out.write_text(
        f"<!doctype html><meta charset='utf-8'><title>Preview — {html.escape(title)}</title>"
        f"<body style='max-width:900px;margin:24px auto;padding:0 16px'>{''.join(parts)}</body>",
        encoding="utf-8",
    )
    print(f"✓ Preview written: {out}")
    return out
