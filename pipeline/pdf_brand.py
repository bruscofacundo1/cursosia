"""Branded per-session PDF (downloadable study material).

Fixed template — only the lesson content changes:
- Header (every page): logo top-right.
- Footer (every page): website bottom-left, page number bottom-right.
- Typography: Roboto (Regular/Bold/Italic embedded from assets/fonts/).
- Palette: same BRAND colors as the HTML lessons.

Renderer: xhtml2pdf (pure Python; WeasyPrint needs GTK DLLs on Windows, which
would complicate the Railway deploy later). It supports the inline-styled HTML
the LLM produces plus @page frames for header/footer.
"""

import io
from pathlib import Path

from xhtml2pdf import pisa
from xhtml2pdf.files import pisaFileObject

from .branding import ASSETS_DIR, BRAND, strip_leading_title

# Windows workaround: xhtml2pdf copies local resources (fonts, images) to a
# NamedTemporaryFile it keeps open, and reportlab then can't reopen it
# (PermissionError). Serving the original local path skips the temp copy.
pisaFileObject.getNamedFile = lambda self: self.uri

_FONTS_DIR = ASSETS_DIR / "fonts"

_PAGE_TEMPLATE = """
<html>
<head>
<style>
    @font-face {{ font-family: Roboto; src: url('{font_regular}'); }}
    @font-face {{ font-family: Roboto; src: url('{font_bold}'); font-weight: bold; }}
    @font-face {{ font-family: Roboto; src: url('{font_italic}'); font-style: italic; }}
    @page {{
        size: a4 portrait;
        margin: 2.6cm 1.8cm 2.2cm 1.8cm;
        @frame header_frame {{
            -pdf-frame-content: header_content;
            top: 0.6cm; left: 1.8cm; width: 17.4cm; height: 1.5cm;
        }}
        @frame footer_frame {{
            -pdf-frame-content: footer_content;
            bottom: 0.6cm; left: 1.8cm; width: 17.4cm; height: 0.9cm;
        }}
    }}
    body {{ font-family: Roboto; font-size: 10.5pt; color: #222222; line-height: 1.5; }}
    h1, h2, h3, h4 {{ font-family: Roboto; color: {color_secondary}; }}
    table {{ font-size: 9.5pt; }}
</style>
</head>
<body>
    <div id="header_content" style="text-align: right;">
        <img src="{logo_path}" style="height: 1.1cm;"/>
    </div>
    <div id="footer_content">
        <table width="100%" style="font-size: 8.5pt; color: #888888;">
            <tr>
                <td align="left">{website}</td>
                <td align="right">Página <pdf:pagenumber/> de <pdf:pagecount/></td>
            </tr>
        </table>
    </div>

    <div style="border-bottom: 2pt solid {color_primary}; padding-bottom: 8pt; margin-bottom: 16pt;">
        <h1 style="color: {color_secondary}; font-size: 17pt; margin: 0;">{session_title}</h1>
        <p style="color: #666666; font-size: 10pt; margin: 2pt 0 0 0;">{course_title} — Sesión {session_number}</p>
    </div>

    {content}

    <p style="font-size: 8.5pt; color: #999999; margin-top: 24pt; border-top: 0.5pt solid #dddddd; padding-top: 6pt;">
        {company} — Material de capacitación interna
    </p>
</body>
</html>
"""


_PDF_LOGO_WIDTH = 1000  # px; header shows it ~1.1cm tall, full-res would bloat every PDF


def _pdf_logo_path() -> Path:
    """Downscaled copy of the logo for the PDF header (cached in assets/)."""
    out = ASSETS_DIR / "logo_pdf.png"
    if not out.exists():
        import fitz  # PyMuPDF

        src = fitz.Pixmap(BRAND["LOGO_PATH"])
        scale = _PDF_LOGO_WIDTH / src.width
        small = fitz.Pixmap(src, _PDF_LOGO_WIDTH, int(src.height * scale), None)
        out.write_bytes(small.tobytes("png"))
    return out


def build_session_pdf(html_content: str, *, course_title: str, session_title: str, session_number: int) -> bytes:
    """Render one session's lesson HTML into the branded PDF. Returns PDF bytes."""
    html_content = strip_leading_title(html_content, session_title)
    for key in ("COLOR_PRIMARY", "COLOR_SECONDARY", "COLOR_ACCENT"):
        html_content = html_content.replace("{{" + key + "}}", BRAND[key])

    doc = _PAGE_TEMPLATE.format(
        font_regular=(_FONTS_DIR / "Roboto-Regular.ttf").as_posix(),
        font_bold=(_FONTS_DIR / "Roboto-Bold.ttf").as_posix(),
        font_italic=(_FONTS_DIR / "Roboto-Italic.ttf").as_posix(),
        logo_path=_pdf_logo_path().as_posix(),
        website=BRAND["WEBSITE_URL"].removeprefix("https://").rstrip("/"),
        company=BRAND["COMPANY_NAME"],
        color_primary=BRAND["COLOR_PRIMARY"],
        color_secondary=BRAND["COLOR_SECONDARY"],
        session_title=session_title,
        course_title=course_title,
        session_number=session_number,
        content=html_content,
    )

    buf = io.BytesIO()
    result = pisa.CreatePDF(doc, dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF rendering failed for session {session_number} ({result.err} error(s)).")
    return buf.getvalue()
