"""PDF → structured text chunks (PyMuPDF).

Output: list of {"chunk_id", "source_file", "pages", "text"} dicts.
Chunks are what Pass 1 receives (all of them) and Pass 2 receives (per session).

Chunking strategy (v1, simple and predictable):
- One chunk per N pages (default 3) per file.
- chunk_id = "<file-stem>_p<start>-<end>" so Claude can reference them and the
  session→chunks mapping stays human-readable.

TODO(claude-code): if source PDFs turn out to have a clean heading structure
(font-size based), switch to heading-based chunking for better session mapping.
TODO(claude-code): scanned PDFs → detect (page.get_text() empty) and warn the
user that OCR is needed (out of MVP scope, do not silently produce empty chunks).
"""

from pathlib import Path

import fitz  # PyMuPDF

PAGES_PER_CHUNK = 3


def extract_chunks(pdf_paths: list[Path], pages_per_chunk: int = PAGES_PER_CHUNK) -> list[dict]:
    chunks: list[dict] = []
    for path in pdf_paths:
        doc = fitz.open(path)
        stem = path.stem.replace(" ", "_")[:40]
        empty_pages = 0

        for start in range(0, doc.page_count, pages_per_chunk):
            end = min(start + pages_per_chunk, doc.page_count)
            text_parts = []
            for pno in range(start, end):
                page_text = doc[pno].get_text("text").strip()
                if not page_text:
                    empty_pages += 1
                text_parts.append(page_text)
            text = "\n\n".join(tp for tp in text_parts if tp)
            if not text:
                continue
            chunks.append(
                {
                    "chunk_id": f"{stem}_p{start + 1}-{end}",
                    "source_file": path.name,
                    "pages": f"{start + 1}-{end}",
                    "text": text,
                }
            )
        doc.close()

        if empty_pages:
            print(
                f"⚠️  {path.name}: {empty_pages} page(s) with no extractable text "
                f"(scanned PDF? OCR is not implemented in the MVP)."
            )

    if not chunks:
        raise ValueError("No text could be extracted from the provided PDF(s).")

    print(f"✓ Extracted {len(chunks)} chunk(s) from {len(pdf_paths)} file(s).")
    return chunks


def chunks_as_prompt_block(chunks: list[dict]) -> str:
    """Render chunks in the format both prompts expect."""
    parts = []
    for c in chunks:
        parts.append(
            f'<fragmento chunk_id="{c["chunk_id"]}" archivo="{c["source_file"]}" paginas="{c["pages"]}">\n'
            f"{c['text']}\n"
            f"</fragmento>"
        )
    return "\n\n".join(parts)
