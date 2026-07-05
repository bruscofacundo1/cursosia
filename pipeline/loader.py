"""Odoo XML-RPC loader: course JSON → slide.channel + sections + slides + quizzes.

Field names verified against the real instance (saas~19.3+e) on 2026-07-04 via
`python scripts/fields_get.py` — full dump in scripts/fields_output.json.

Design:
- Idempotent-friendly: refuses to create a course whose name already exists
  unless force=True (then the old one is unlinked first).
- Transactional-ish: if anything fails mid-load, the created channel is
  unlinked (cascade removes its slides/questions) so no half-loaded courses.
"""

import base64
import os
import xmlrpc.client

from .branding import apply_branding
from .pdf_brand import build_session_pdf


class OdooClient:
    def __init__(self):
        self.url = os.environ["ODOO_URL"].rstrip("/")
        self.db = os.environ["ODOO_DB"]
        self.user = os.environ["ODOO_USER"]
        self.key = os.environ["ODOO_API_KEY"]

        common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.user, self.key, {})
        if not self.uid:
            raise RuntimeError("Odoo authentication failed: check ODOO_* env vars.")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    def call(self, model: str, method: str, *args, **kwargs):
        return self._models.execute_kw(self.db, self.uid, self.key, model, method, list(args), kwargs)

    # -- convenience wrappers --
    def create(self, model: str, vals: dict) -> int:
        # create() gets a list of vals dicts and thus returns a list of ids
        return self.call(model, "create", [vals])[0]

    def search(self, model: str, domain: list, **kw) -> list[int]:
        return self.call(model, "search", domain, **kw)

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.call(model, "unlink", ids)


def load_course(
    course: dict,
    *,
    publish: bool = False,
    force: bool = False,
    with_pdf: bool = True,
    cover_image: str | None = None,
) -> int:
    """Load a generated course JSON into Odoo. Returns the channel id.

    cover_image: optional path to an image file used as the course card
    picture (slide.channel.image_1920; Odoo derives the smaller sizes).
    """
    odoo = OdooClient()
    structure = course["structure"]
    title = structure["title"]

    existing = odoo.search("slide.channel", [["name", "=", title]])
    if existing:
        if not force:
            raise RuntimeError(
                f"A course named '{title}' already exists (ids {existing}). Use --force to replace it."
            )
        print(f"⚠️  Removing existing course(s) {existing} (--force).")
        odoo.unlink("slide.channel", existing)

    print(f"→ Creating course '{title}' (published={publish})...")
    # 'description' is an html field: format as HTML, plain \n would collapse.
    objectives_html = "".join(f"<li>{o}</li>" for o in structure["objectives"])
    description = (
        f"<p>{structure['description']}</p>"
        f"<p><strong>Objetivos:</strong></p><ul>{objectives_html}</ul>"
    )

    channel_vals = {
        "name": title,
        "description": description,
        "is_published": publish,
        "enroll": "invite",  # saas-19.3 selection: 'public' | 'invite' (no 'payment' on this plan)
        "channel_type": "training",  # required selection: 'training' | 'documentation'
    }
    if cover_image:
        with open(cover_image, "rb") as fh:
            channel_vals["image_1920"] = base64.b64encode(fh.read()).decode("ascii")

    channel_id = odoo.create("slide.channel", channel_vals)

    try:
        seq = 10
        for structure_session, content in zip(
            sorted(structure["sessions"], key=lambda s: s["number"]), course["sessions"]
        ):
            n = structure_session["number"]

            # Section separator
            odoo.create(
                "slide.slide",
                {
                    "name": f"Sesión {n}: {structure_session['title']}",
                    "channel_id": channel_id,
                    "is_category": True,
                    "sequence": seq,
                },
            )
            seq += 1

            # Lesson (article with branded HTML)
            branded_html = apply_branding(
                content["html_content"],
                course_title=title,
                session_title=content["title"],
                session_number=n,
            )
            slide_id = odoo.create(
                "slide.slide",
                {
                    "name": content["title"],
                    "channel_id": channel_id,
                    "slide_category": "article",
                    "html_content": branded_html,
                    "sequence": seq,
                    "is_published": publish,
                },
            )
            seq += 1

            # Branded PDF (study material) as a document slide.
            if with_pdf:
                pdf_bytes = build_session_pdf(
                    content["html_content"],
                    course_title=title,
                    session_title=content["title"],
                    session_number=n,
                )
                odoo.create(
                    "slide.slide",
                    {
                        "name": f"Material de estudio — {content['title']}",
                        "channel_id": channel_id,
                        "slide_category": "document",
                        "source_type": "local_file",
                        "binary_content": base64.b64encode(pdf_bytes).decode("ascii"),
                        "sequence": seq,
                        "is_published": publish,
                    },
                )
                seq += 1

            # Quiz: slide.question records attached directly to the article
            # slide (slide.slide.question_ids exists in saas-19.3; Odoo shows
            # the quiz at the end of the lesson). No separate quiz slide.
            for q_seq, q in enumerate(content["quiz"], start=1):
                question_id = odoo.create(
                    "slide.question",
                    {"slide_id": slide_id, "question": q["question"], "sequence": q_seq},
                )
                for a in q["answers"]:
                    odoo.create(
                        "slide.answer",
                        {
                            "question_id": question_id,
                            "text_value": a["text"],
                            "is_correct": a["is_correct"],
                            "comment": a.get("feedback", ""),
                        },
                    )
            print(
                f"  ✓ Session {n} loaded ({len(content['quiz'])} quiz questions"
                + (", branded PDF" if with_pdf else "")
                + ")."
            )

        print(f"✓ Course loaded. Channel id: {channel_id}")
        print(f"  Backend: {odoo.url}/odoo/action-website_slides.slide_channel_action_overview")
        return channel_id

    except Exception:
        print("✗ Load failed mid-way — rolling back (unlinking channel)...")
        try:
            odoo.unlink("slide.channel", [channel_id])
            print("  ✓ Rollback done.")
        except Exception as rollback_exc:  # noqa: BLE001
            print(f"  ⚠️  Rollback ALSO failed ({rollback_exc}); delete channel {channel_id} manually.")
        raise
