"""PDF → structured text chunks (PyMuPDF).

Output: list of {"chunk_id", "source_file", "pages", "heading", "text"} dicts.
Chunks are what Pass 1 receives (all of them) and Pass 2 receives (per session).

Chunking strategy (v2 — structural):
1. Detect section headings by typography (font size / bold vs. body text) plus
   regex for normative markers ("Artículo 12", "CAPÍTULO III", "3.2 Título").
2. Cut the document at headings so each chunk is a semantic unit — an article
   of the norm never gets split mid-sentence across chunks, which keeps the
   session→source mapping and the citations precise.
3. Small consecutive sections are merged; oversized ones are split at
   paragraph boundaries.
4. If the document shows no usable heading structure, fall back to the v1
   fixed pages-per-chunk strategy (predictable, always works).

Scanned PDFs (no extractable text) are detected and reported: OCR is out of
MVP scope and silently producing empty chunks would be worse.
"""

import re
import statistics
from pathlib import Path

import fitz  # PyMuPDF

PAGES_PER_CHUNK = 3          # fallback strategy
MAX_CHUNK_CHARS = 6000       # split sections bigger than this
MIN_CHUNK_CHARS = 800        # merge sections smaller than this
MIN_HEADINGS_FOR_STRUCTURAL = 3

_HEADING_MARKER_RE = re.compile(
    r"^\s*(art[ií]culo\s+\d+|cap[ií]tulo\s+([IVXLCDM]+|\d+)|secci[oó]n\s+([IVXLCDM]+|\d+)"
    r"|anexo\s+([IVXLCDM]+|\d+)|t[ií]tulo\s+([IVXLCDM]+|\d+)|\d+(\.\d+)*[\.\)]?\s+\S)",
    re.IGNORECASE,
)


def _collect_lines(doc: fitz.Document) -> tuple[list[dict], float]:
    """Flatten the document into ordered lines with typography info.
    Returns (lines, body_font_size)."""
    lines: list[dict] = []
    sizes: list[float] = []
    for pno in range(doc.page_count):
        for block in doc[pno].get_text("dict")["blocks"]:
            if block.get("type") != 0:  # text blocks only
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                max_size = max(s["size"] for s in spans)
                all_bold = all(s["flags"] & 16 for s in spans)  # bit 4 = bold
                lines.append({"page": pno + 1, "text": text, "size": max_size, "bold": all_bold})
                sizes.append(max_size)
    body_size = statistics.median(sizes) if sizes else 11.0
    return lines, body_size


def _is_heading(line: dict, body_size: float) -> bool:
    text = line["text"]
    if len(text) > 120:
        return False
    bigger = line["size"] >= body_size * 1.15
    bold_same = line["bold"] and line["size"] >= body_size * 0.98
    marker = bool(_HEADING_MARKER_RE.match(text))
    if marker and (bigger or bold_same):
        return True
    if bigger and len(text) <= 90 and not text.endswith("."):
        return True
    return False


def _structural_sections(doc: fitz.Document) -> list[dict] | None:
    """Split the document at detected headings. None if structure is too weak."""
    lines, body_size = _collect_lines(doc)
    if not lines:
        return None

    heading_idx = [i for i, ln in enumerate(lines) if _is_heading(ln, body_size)]
    if len(heading_idx) < MIN_HEADINGS_FOR_STRUCTURAL:
        return None

    sections: list[dict] = []
    # Preamble before the first heading.
    bounds = [0] + heading_idx + [len(lines)]
    if heading_idx[0] > 0:
        pre = lines[: heading_idx[0]]
        sections.append({
            "heading": "Introducción / portada",
            "pages": (pre[0]["page"], pre[-1]["page"]),
            "text": "\n".join(ln["text"] for ln in pre),
        })
    for a, b in zip(heading_idx, heading_idx[1:] + [len(lines)]):
        chunk_lines = lines[a:b]
        sections.append({
            "heading": lines[a]["text"][:100],
            "pages": (chunk_lines[0]["page"], chunk_lines[-1]["page"]),
            "text": "\n".join(ln["text"] for ln in chunk_lines),
        })
    return sections


def _pack_sections(sections: list[dict]) -> list[dict]:
    """Merge tiny sections with the previous one; split oversized ones."""
    packed: list[dict] = []
    for sec in sections:
        if packed and len(sec["text"]) < MIN_CHUNK_CHARS and len(packed[-1]["text"]) + len(sec["text"]) <= MAX_CHUNK_CHARS:
            prev = packed[-1]
            prev["text"] += "\n\n" + sec["text"]
            prev["pages"] = (prev["pages"][0], sec["pages"][1])
            continue
        packed.append(dict(sec))

    result: list[dict] = []
    for sec in packed:
        if len(sec["text"]) <= MAX_CHUNK_CHARS:
            result.append(sec)
            continue
        # Split at paragraph boundaries.
        paragraphs = sec["text"].split("\n")
        part: list[str] = []
        part_no = 1
        for p in paragraphs:
            part.append(p)
            if sum(len(x) for x in part) >= MAX_CHUNK_CHARS:
                result.append({
                    "heading": f"{sec['heading']} (parte {part_no})",
                    "pages": sec["pages"],
                    "text": "\n".join(part),
                })
                part, part_no = [], part_no + 1
        if part:
            heading = sec["heading"] if part_no == 1 else f"{sec['heading']} (parte {part_no})"
            result.append({"heading": heading, "pages": sec["pages"], "text": "\n".join(part)})
    return result


def extract_chunks(pdf_paths: list[Path], pages_per_chunk: int = PAGES_PER_CHUNK) -> list[dict]:
    chunks: list[dict] = []
    for path in pdf_paths:
        doc = fitz.open(path)
        stem = Path(path).stem.replace(" ", "_")[:40]

        empty_pages = sum(1 for pno in range(doc.page_count) if not doc[pno].get_text("text").strip())
        if empty_pages:
            print(
                f"⚠️  {Path(path).name}: {empty_pages} page(s) with no extractable text "
                f"(scanned PDF? OCR is not implemented in the MVP)."
            )

        sections = _structural_sections(doc)
        if sections:
            sections = _pack_sections(sections)
            for i, sec in enumerate(sections, start=1):
                chunks.append({
                    "chunk_id": f"{stem}_s{i:02d}",
                    "source_file": Path(path).name,
                    "pages": f"{sec['pages'][0]}-{sec['pages'][1]}",
                    "heading": sec["heading"],
                    "text": sec["text"],
                })
            print(f"✓ {Path(path).name}: structural chunking — {len(sections)} section(s) detected.")
        else:
            # Fallback: fixed pages-per-chunk (v1 behaviour).
            for start in range(0, doc.page_count, pages_per_chunk):
                end = min(start + pages_per_chunk, doc.page_count)
                text = "\n\n".join(
                    t for t in (doc[p].get_text("text").strip() for p in range(start, end)) if t
                )
                if not text:
                    continue
                chunks.append({
                    "chunk_id": f"{stem}_p{start + 1}-{end}",
                    "source_file": Path(path).name,
                    "pages": f"{start + 1}-{end}",
                    "heading": f"Páginas {start + 1}-{end}",
                    "text": text,
                })
            print(f"✓ {Path(path).name}: no clear heading structure — page-based chunking.")
        doc.close()

    if not chunks:
        raise ValueError("No text could be extracted from the provided PDF(s).")

    print(f"✓ Extracted {len(chunks)} chunk(s) from {len(pdf_paths)} file(s).")
    return chunks


def chunks_as_prompt_block(chunks: list[dict]) -> str:
    """Render chunks in the format both prompts expect."""
    parts = []
    for c in chunks:
        heading = f' titulo="{c["heading"]}"' if c.get("heading") else ""
        parts.append(
            f'<fragmento chunk_id="{c["chunk_id"]}" archivo="{c["source_file"]}" paginas="{c["pages"]}"{heading}>\n'
            f"{c['text']}\n"
            f"</fragmento>"
        )
    return "\n\n".join(parts)
