"""Convert broker/analyst PDF reports to Markdown using Gemini vision.

Sends the raw PDF bytes to the Gemini REST API so tables, charts, and layout
survive intact, then writes clean Markdown (with every figure preserved).

API key handling follows AGENTS.md rule 1: the key is read strictly from the
GEMINI_API_KEY environment variable (or a local .env via python-dotenv). It is
never hardcoded and never passed via argv.
"""

import base64
import json
import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-flash-lite-latest"
MAX_INLINE_BYTES = 20 * 1024 * 1024  # inlineData cap for the Public API

PROMPT = (
    "Convert this analyst report to Markdown. Reproduce EVERY table as a "
    "Markdown table (rating, P/E, EPS, price targets, upside). Preserve all "
    "numbers exactly, keep headings and document order, and flag any figure "
    "you cannot read with the exact marker [could not read] instead of "
    "guessing. Do not invent data."
)


class Pdf2mdError(Exception):
    """Raised for any failure reading or converting a PDF."""


_CP1252_PUNCT = {
    0x80: "\u20ac", 0x82: "\u201a", 0x83: "\u0192", 0x84: "\u201e",
    0x85: "\u2026", 0x86: "\u2020", 0x87: "\u2021", 0x88: "\u02c6",
    0x89: "\u2030", 0x8a: "\u0160", 0x8b: "\u2039", 0x8c: "\u0152",
    0x8e: "\u017d", 0x91: "\u2018", 0x92: "\u2019", 0x93: "\u201c",
    0x94: "\u201d", 0x95: "\u2022", 0x96: "\u2013", 0x97: "\u2014",
    0x98: "\u02dc", 0x99: "\u2122", 0x9a: "\u0161", 0x9b: "\u203a",
    0x9c: "\u0153", 0x9e: "\u017e", 0x9f: "\u0178",
}


def clean_punctuation(text: str) -> str:
    """Fix stray Windows-1252 control-range punctuation to proper Unicode."""
    return "".join(_CP1252_PUNCT.get(ord(ch), ch) for ch in text)


def resolve_api_key() -> str:
    """Return the Gemini API key from the environment (never argv)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key and load_dotenv:
        load_dotenv()
        key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise Pdf2mdError(
            "GEMINI_API_KEY is not set. Create a free key (no credit card) at "
            "https://aistudio.google.com/apikey then run:\n\n"
            "  setx GEMINI_API_KEY <your-key>\n\n"
            "and restart the terminal before rerunning."
        )
    return key


def generate_markdown(pdf_bytes: bytes, api_key: str, model: str = DEFAULT_MODEL) -> str:
    """Send raw PDF bytes to Gemini and return the Markdown conversion."""
    if len(pdf_bytes) > MAX_INLINE_BYTES:
        raise Pdf2mdError(
            f"PDF is {len(pdf_bytes) / 1e6:.1f} MB; the inline limit is "
            f"{MAX_INLINE_BYTES // (1024 * 1024)} MB. Split the file first."
        )
    if not pdf_bytes.strip():
        raise Pdf2mdError("PDF is empty (0 bytes).")

    url = f"{API_BASE}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": base64.b64encode(pdf_bytes).decode("ascii"),
                        }
                    },
                    {"text": PROMPT},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 8192},
    }

    resp = requests.post(url, params={"key": api_key}, json=payload, timeout=120)
    try:
        body = resp.json()
    except ValueError as exc:
        raise Pdf2mdError(f"Gemini API returned non-JSON content (HTTP {resp.status_code}).") from exc

    # AGENTS.md rule 2: guard against HTTP 200 OK error payloads.
    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        message = err.get("message", "unknown error")
        hint = ""
        if "not found" in message or "not supported" in message:
            hint = (
                "\n\nModel id may be outdated. Pin one from AI Studio via "
                "setx GEMINI_PDF_MODEL <model-id> (model names rotate)."
            )
        raise Pdf2mdError(f"Gemini API error: {err.get('code')} {err.get('status')}: {message}{hint}")
    if resp.status_code != 200:
        raise Pdf2mdError(f"Gemini API HTTP {resp.status_code}: {json.dumps(body)[:500]}")

    candidates = body.get("candidates") or []
    if not candidates:
        raise Pdf2mdError("Gemini returned no candidates.")
    try:
        text = "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
        )
    except (AttributeError, TypeError) as exc:
        raise Pdf2mdError("Unexpected Gemini response shape.") from exc
    if not text.strip():
        raise Pdf2mdError("Gemini returned an empty response.")
    return clean_punctuation(text)


def convert_pdf(path: str, model: str | None = None, out_path: str | None = None) -> Path:
    """Convert a PDF file to Markdown and write it next to the input by default."""
    src = Path(path)
    if not src.exists():
        raise Pdf2mdError(f"File not found: {src}")
    if src.suffix.lower() != ".pdf":
        raise Pdf2mdError(f"Not a PDF file: {src}")

    model = model or os.environ.get("GEMINI_PDF_MODEL") or DEFAULT_MODEL
    api_key = resolve_api_key()
    text = generate_markdown(src.read_bytes(), api_key, model)

    if out_path:
        dst = Path(out_path)
        if dst.suffix.lower() != ".md":
            dst = dst.with_suffix(".md")
    else:
        dst = src.with_name(f"{src.stem}_pdf2md.md")
    dst.write_text(text, encoding="utf-8")
    return dst


def _reconfigure_stdio() -> None:
    """Keep Windows consoles from crashing on non-cp1252 glyphs (e.g. stars)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: python -m finance.pdf2md <report.pdf> [model] [output.md]")
        return 0

    path = argv[0]
    model = argv[1] if len(argv) > 1 else None
    out_path = argv[2] if len(argv) > 2 else None
    resolved_model = model or os.environ.get("GEMINI_PDF_MODEL") or DEFAULT_MODEL
    try:
        dst = convert_pdf(path, model, out_path)
    except Pdf2mdError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Converted {path} -> {dst} (model={resolved_model})", file=sys.stderr)
    print(dst.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())