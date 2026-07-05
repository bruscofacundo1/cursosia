"""JSON schemas for validating Claude's structured outputs.

Pass 1 (course structure) and Pass 2 (session content) each have a schema.
Every Claude response MUST validate against its schema before moving on.
"""

# --- Pass 1: course structure -------------------------------------------------

COURSE_STRUCTURE_SCHEMA = {
    "type": "object",
    "required": ["title", "description", "objectives", "sessions"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 3},
        "description": {
            "type": "string",
            "description": "Short course description shown on the Odoo course card (2-3 sentences, Spanish).",
        },
        "objectives": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "sessions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["number", "title", "topics", "source_chunk_ids"],
                "additionalProperties": False,
                "properties": {
                    "number": {"type": "integer", "minimum": 1},
                    "title": {"type": "string"},
                    "topics": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "source_chunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "IDs of source-material chunks this session must be grounded on.",
                    },
                },
            },
        },
    },
}

# --- Pass 2: one session's content --------------------------------------------

SESSION_CONTENT_SCHEMA = {
    "type": "object",
    "required": ["session_number", "title", "html_content", "quiz"],
    "additionalProperties": False,
    "properties": {
        "session_number": {"type": "integer", "minimum": 1},
        "title": {"type": "string"},
        "html_content": {
            "type": "string",
            "minLength": 200,
            "description": (
                "Full lesson body as HTML with INLINE styles only (no <script>, no "
                "external CSS, no <html>/<head>/<body> wrappers). Uses the branding "
                "palette placeholders defined in branding.py."
            ),
        },
        "quiz": {
            "type": "array",
            "minItems": 3,
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["question", "answers"],
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string", "minLength": 10},
                    "answers": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "required": ["text", "is_correct"],
                            "additionalProperties": False,
                            "properties": {
                                "text": {"type": "string"},
                                "is_correct": {"type": "boolean"},
                                "feedback": {
                                    "type": "string",
                                    "description": "Explanation shown to the participant (Spanish). Cite the source section when possible.",
                                },
                            },
                        },
                    },
                },
            },
        },
        "unconfirmed_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Anything the source material did not cover but seemed necessary. "
                "These are flagged '(a confirmar)' in the preview for human review. "
                "NEVER invented content: this list is the escape hatch."
            ),
        },
    },
}


def validate_exactly_one_correct(session: dict) -> list[str]:
    """Extra semantic check jsonschema can't express: each question must have
    exactly one correct answer (Odoo quiz behaviour). Returns list of errors."""
    errors = []
    for i, q in enumerate(session.get("quiz", []), start=1):
        correct = sum(1 for a in q["answers"] if a["is_correct"])
        if correct != 1:
            errors.append(
                f"Question {i} ('{q['question'][:50]}...') has {correct} correct answers, expected exactly 1."
            )
    return errors
