"""Automatic citation verification (anti-hallucination net #2).

The prompts demand citing the source ("según el art. 12..."). This module
extracts those citations from the generated lesson HTML and checks each one
actually appears in the session's assigned source chunks. Citations that can't
be matched are flagged and surfaced with the "(a confirmar)" points in the
human-review preview — turning the reviewer's job from "distrust everything"
into "check what's flagged".

Conservative by design: a flag means "please verify", not "this is wrong"
(the source may phrase the reference differently).
"""

import re

# Citation kinds and the spelling variants they may take in the source text.
_KIND_VARIANTS: dict[str, list[str]] = {
    "articulo": [r"art[ií]culos?", r"arts?\."],
    "seccion": [r"secci[oó]n(?:es)?", r"secc?\."],
    "capitulo": [r"cap[ií]tulos?", r"cap\."],
    "anexo": [r"anexos?"],
    "clausula": [r"cl[aá]usulas?"],
    "inciso": [r"incisos?", r"inc\."],
    "apartado": [r"apartados?"],
    "punto": [r"puntos?"],
}

_KIND_ALTERNATION = "|".join(v for vs in _KIND_VARIANTS.values() for v in vs)

# e.g. "art. 12", "Artículo 5.3", "sección IV", "anexo II", "punto 4.1.2"
_CITE_RE = re.compile(
    rf"\b({_KIND_ALTERNATION})\s+(\d+(?:\.\d+)*|[IVXLCDM]+)\b",
    re.IGNORECASE,
)

# e.g. "pág. 2", "página 14" — checked against the chunks' page ranges.
_PAGE_RE = re.compile(r"\bp[aá]g(?:ina)?\.?\s+(\d+)\b", re.IGNORECASE)


def _kind_key(matched: str) -> str:
    """Map a matched kind spelling back to its canonical key."""
    low = matched.lower()
    for key, variants in _KIND_VARIANTS.items():
        for v in variants:
            if re.fullmatch(v, low, re.IGNORECASE):
                return key
    return low


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def verify_citations(html_content: str, session_chunks: list[dict]) -> list[str]:
    """Return human-readable flags for citations not found in the source."""
    source = " ".join(c["text"] for c in session_chunks)
    text = _strip_tags(html_content)
    flags: list[str] = []
    seen: set[tuple[str, str]] = set()

    for m in _CITE_RE.finditer(text):
        kind, ref = _kind_key(m.group(1)), m.group(2)
        if (kind, ref.lower()) in seen:
            continue
        seen.add((kind, ref.lower()))
        variants = _KIND_VARIANTS.get(kind, [re.escape(kind)])
        found = any(
            re.search(rf"\b(?:{v})\s*{re.escape(ref)}\b", source, re.IGNORECASE)
            for v in variants
        )
        if not found:
            flags.append(
                f'Cita no verificada en el material fuente: "{m.group(0)}" '
                f"(revisar que la referencia exista y sea correcta)"
            )

    # Page citations: check against the page ranges of the assigned chunks.
    pages_covered: set[int] = set()
    for c in session_chunks:
        start, _, end = str(c.get("pages", "")).partition("-")
        if start.isdigit():
            pages_covered.update(range(int(start), int(end or start) + 1))
    if pages_covered:
        for m in _PAGE_RE.finditer(text):
            page = int(m.group(1))
            if page not in pages_covered and ("pag", str(page)) not in seen:
                seen.add(("pag", str(page)))
                flags.append(
                    f'Cita no verificada: "{m.group(0)}" — la página {page} no está '
                    f"entre las páginas del material asignado a esta sesión "
                    f"({min(pages_covered)}-{max(pages_covered)})"
                )

    return flags
