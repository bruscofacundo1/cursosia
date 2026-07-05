"""Client branding: palette, logo, and lesson HTML wrapper.

GerenciAndo Canales brand. Palette sampled from assets/logo.png (2026-07-05):
wordmark purple, dark plum, deep gradient purple (gradient runs #6D2998→#C68FCE).
Brand typography is Roboto; Odoo lesson HTML can only use inline styles, so we
declare a Roboto-first stack with safe fallbacks (the exact font is embedded in
the branded PDFs, see pdf_brand.py).
"""

import base64
import re
from functools import lru_cache
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "assets"

BRAND = {
    "COLOR_PRIMARY": "#9B55A7",     # wordmark purple
    "COLOR_SECONDARY": "#402343",   # dark plum ('Canales')
    "COLOR_ACCENT": "#6D2998",      # deep gradient purple
    "LOGO_PATH": str(ASSETS_DIR / "logo.png"),  # full-res, used by pdf_brand.py
    "COMPANY_NAME": "Gerenciando Canales - Consultora",
    "WEBSITE_URL": "https://gerenciandocanales.com.ar/",
    "FONT_STACK": "Roboto, 'Helvetica Neue', Arial, Helvetica, sans-serif",
}

_LOGO_WEB_WIDTH = 480  # px; rendered at ~48px height, so 480 wide is plenty


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """Downscaled logo as a data URI (~27 KB). Embedded directly in lesson HTML:
    Odoo SaaS serves loose attachments as placeholders to non-logged users, and
    its html sanitizer keeps data:image URIs (verified on saas-19.3), so this is
    the reliable way to show the logo. Empty string if the asset is missing."""
    path = Path(BRAND["LOGO_PATH"])
    if not path.exists():
        return ""
    import fitz  # PyMuPDF

    src = fitz.Pixmap(str(path))
    scale = _LOGO_WEB_WIDTH / src.width
    web = fitz.Pixmap(src, _LOGO_WEB_WIDTH, int(src.height * scale), None)
    return "data:image/png;base64," + base64.b64encode(web.tobytes("png")).decode("ascii")

_LESSON_WRAPPER = """
<div style="font-family: {font}; color: #222; max-width: 860px; margin: 0 auto; line-height: 1.6;">
  {logo_block}
  <div style="border-left: 4px solid {COLOR_PRIMARY}; padding-left: 16px; margin-bottom: 24px;">
    <h2 style="color: {COLOR_SECONDARY}; margin: 0;">{session_title}</h2>
    <p style="color: #666; margin: 4px 0 0 0; font-size: 14px;">{course_title} — Sesión {session_number}</p>
  </div>
  {content}
  <hr style="border: none; border-top: 1px solid #ddd; margin-top: 32px;"/>
  <p style="font-size: 12px; color: #999; text-align: center;">
    {company} — Material de capacitación interna ·
    <a href="{website}" style="color: {COLOR_PRIMARY}; text-decoration: none;">{website_label}</a>
  </p>
</div>
"""

_LOGO_BLOCK = '<div style="text-align: right; margin-bottom: 16px;"><img src="{url}" alt="logo" style="max-height: 48px;"/></div>'


def strip_leading_title(html_content: str, session_title: str) -> str:
    """Drop a leading <h1-3> that repeats the session title: both the lesson
    wrapper and the PDF template already render the title themselves."""
    pattern = (
        r"^\s*<h[1-3][^>]*>\s*" + re.escape(session_title.strip()) + r"\s*</h[1-3]>"
    )
    return re.sub(pattern, "", html_content, count=1, flags=re.IGNORECASE)


def apply_branding(html_content: str, *, course_title: str, session_title: str, session_number: int) -> str:
    """Replace {{COLOR_*}} placeholders and wrap the lesson in the branded shell."""
    html_content = strip_leading_title(html_content, session_title)
    for key in ("COLOR_PRIMARY", "COLOR_SECONDARY", "COLOR_ACCENT"):
        html_content = html_content.replace("{{" + key + "}}", BRAND[key])

    logo = logo_data_uri()
    logo_block = _LOGO_BLOCK.format(url=logo) if logo else ""

    return _LESSON_WRAPPER.format(
        logo_block=logo_block,
        font=BRAND["FONT_STACK"],
        COLOR_PRIMARY=BRAND["COLOR_PRIMARY"],
        COLOR_SECONDARY=BRAND["COLOR_SECONDARY"],
        session_title=session_title,
        course_title=course_title,
        session_number=session_number,
        content=html_content,
        company=BRAND["COMPANY_NAME"],
        website=BRAND["WEBSITE_URL"],
        website_label=BRAND["WEBSITE_URL"].removeprefix("https://").rstrip("/"),
    )
