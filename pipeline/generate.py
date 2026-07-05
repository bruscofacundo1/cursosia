"""LLM API calls: Pass 1 (structure) + Pass 2 (per-session content).

Default provider is Claude (Anthropic) per the architecture decision. A
temporary Gemini fallback exists for development while there is no Anthropic
API key (LLM_PROVIDER=gemini in .env); the prompts, schemas and retry logic
are provider-agnostic, only the transport changes.

Every response is parsed as JSON and validated against its schema. On failure:
one retry with the validation errors appended. On second failure: raise.
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic
from jsonschema import Draft202012Validator

from .extract import chunks_as_prompt_block
from .prompts import RETRY_SUFFIX, SESSION_SYSTEM_PROMPT, STRUCTURE_SYSTEM_PROMPT
from .schemas import (
    COURSE_STRUCTURE_SCHEMA,
    SESSION_CONTENT_SCHEMA,
    validate_exactly_one_correct,
)
from .verify import verify_citations

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower()
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOKENS_STRUCTURE = 4000
MAX_TOKENS_SESSION = 16000

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _complete_anthropic(system: str, messages: list[dict], max_tokens: int) -> str:
    resp = _get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def _complete_gemini(system: str, messages: list[dict], max_tokens: int) -> str:
    """Temporary dev fallback (stdlib-only, no extra deps). Roles map
    assistant→model; responseMimeType asks Gemini for bare JSON."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set in .env")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    # Free-tier Gemini throws transient 503 (overloaded) / 429 (rate limit)
    # regularly: retry those with backoff before giving up.
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                wait = 8 * attempt
                print(f"  ⚠️  Gemini devolvió {exc.code} (transitorio), reintento {attempt}/{max_attempts - 1} en {wait}s...")
                time.sleep(wait)
                continue
            raise
    parts = data["candidates"][0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _complete(system: str, messages: list[dict], max_tokens: int) -> str:
    if PROVIDER == "gemini":
        return _complete_gemini(system, messages, max_tokens)
    return _complete_anthropic(system, messages, max_tokens)


def _parse_json(raw: str) -> dict:
    """Claude is instructed to return bare JSON, but strip fences defensively."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned.removeprefix("json").strip()
    return json.loads(cleaned)


def _call_validated(system: str, user_content: str, schema: dict, max_tokens: int, extra_checks=None) -> dict:
    """Call the LLM, validate output; retry once with errors on failure."""
    validator = Draft202012Validator(schema)
    messages = [{"role": "user", "content": user_content}]

    for attempt in (1, 2):
        raw = _complete(system, messages, max_tokens)

        errors: list[str] = []
        data: dict | None = None
        try:
            data = _parse_json(raw)
            errors = [f"{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(data)]
            if not errors and extra_checks:
                errors = extra_checks(data)
        except json.JSONDecodeError as exc:
            errors = [f"Invalid JSON: {exc}"]

        if not errors:
            return data  # type: ignore[return-value]

        if attempt == 1:
            print(f"  ⚠️  Validation failed ({len(errors)} error(s)), retrying once...")
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": RETRY_SUFFIX.format(errors="\n".join(f"- {e}" for e in errors))},
            ]

    raise RuntimeError("Claude output failed validation twice:\n" + "\n".join(f"- {e}" for e in errors))


# --- Public API -----------------------------------------------------------------


def generate_structure(chunks: list[dict], title_hint: str | None = None) -> dict:
    print("→ Pass 1: generating course structure...")
    user = ""
    if title_hint:
        user += f"Título tentativo sugerido por el usuario: {title_hint}\n\n"
    user += "MATERIAL FUENTE:\n\n" + chunks_as_prompt_block(chunks)

    structure = _call_validated(STRUCTURE_SYSTEM_PROMPT, user, COURSE_STRUCTURE_SCHEMA, MAX_TOKENS_STRUCTURE)
    print(f"✓ Structure: '{structure['title']}' — {len(structure['sessions'])} session(s).")
    return structure


def generate_session(structure: dict, session: dict, chunks_by_id: dict[str, dict]) -> dict:
    n = session["number"]
    print(f"→ Pass 2: generating session {n}/{len(structure['sessions'])}: {session['title']}...")

    session_chunks = [chunks_by_id[cid] for cid in session["source_chunk_ids"] if cid in chunks_by_id]
    missing = [cid for cid in session["source_chunk_ids"] if cid not in chunks_by_id]
    if missing:
        print(f"  ⚠️  Structure referenced unknown chunk_ids (ignored): {missing}")
    if not session_chunks:
        raise RuntimeError(f"Session {n} has no valid source chunks; aborting (would generate ungrounded content).")

    user = (
        f"ESTRUCTURA GENERAL DEL CURSO:\n{json.dumps(structure, ensure_ascii=False, indent=2)}\n\n"
        f"SESIÓN A GENERAR: número {n} — \"{session['title']}\"\n"
        f"Temas: {', '.join(session['topics'])}\n\n"
        f"MATERIAL FUENTE ASIGNADO A ESTA SESIÓN:\n\n{chunks_as_prompt_block(session_chunks)}"
    )

    content = _call_validated(
        SESSION_SYSTEM_PROMPT,
        user,
        SESSION_CONTENT_SCHEMA,
        MAX_TOKENS_SESSION,
        extra_checks=validate_exactly_one_correct,
    )

    # Anti-hallucination net #2: flag citations not found in the source chunks.
    citation_flags = verify_citations(content["html_content"], session_chunks)
    if citation_flags:
        content.setdefault("unconfirmed_points", []).extend(citation_flags)
        print(f"  ⚠️  {len(citation_flags)} cita(s) sin verificar (marcadas para revisión).")

    print(f"  ✓ Session {n}: {len(content['quiz'])} quiz question(s), "
          f"{len(content.get('unconfirmed_points', []))} point(s) flagged '(a confirmar)'.")
    return content


def course_slug(title: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in title.lower())[:60]


def is_course_complete(course: dict) -> bool:
    return len(course.get("sessions", [])) >= len(course["structure"]["sessions"])


def generate_course(
    chunks: list[dict],
    title_hint: str | None = None,
    *,
    output_dir: Path | None = None,
    resume: dict | None = None,
    on_checkpoint: Callable[[Path], None] | None = None,
) -> dict:
    """Full generation: structure + all sessions. Returns the course JSON.

    output_dir: if given, the course JSON is checkpointed there after the
    structure pass and after EVERY session, so a failure mid-run loses at most
    one session. The saved JSON includes the source chunks, so resuming needs
    nothing but the file: pass it back as `resume`.
    """
    active_model = GEMINI_MODEL if PROVIDER == "gemini" else MODEL
    print(f"→ LLM provider: {PROVIDER} (model {active_model})")

    if resume:
        course = resume
        chunks = course.get("chunks") or chunks
        if not chunks:
            raise RuntimeError("Cannot resume: the JSON has no stored chunks and no PDFs were given.")
        done = len(course.get("sessions", []))
        total = len(course["structure"]["sessions"])
        print(f"→ Resuming '{course['structure']['title']}': {done}/{total} session(s) already generated.")
    else:
        structure = generate_structure(chunks, title_hint)
        course = {
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "provider": PROVIDER,
                "model": active_model,
            },
            "structure": structure,
            "chunks": chunks,
            "sessions": [],
        }

    checkpoint_path: Path | None = None
    if output_dir:
        output_dir.mkdir(exist_ok=True)
        checkpoint_path = output_dir / f"{course_slug(course['structure']['title'])}.json"

    def _save() -> None:
        if checkpoint_path:
            checkpoint_path.write_text(json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8")
            if on_checkpoint:
                on_checkpoint(checkpoint_path)

    _save()

    chunks_by_id = {c["chunk_id"]: c for c in chunks}
    pending = sorted(course["structure"]["sessions"], key=lambda s: s["number"])[len(course["sessions"]):]
    for s in pending:
        course["sessions"].append(generate_session(course["structure"], s, chunks_by_id))
        _save()

    return course
