"""Offline tests for the Gemini-based PDF-to-Markdown converter (pdf2md.py).

All tests mock the network: requests.post is patched, so no API key is used and
no external calls are made. Follows AGENTS.md rule 2 by asserting the HTTP 200
OK error-payload guard.
"""

import pytest

from finance.pdf2md import (
    DEFAULT_MODEL,
    MAX_INLINE_BYTES,
    Pdf2mdError,
    clean_punctuation,
    convert_pdf,
    generate_markdown,
    main,
    resolve_api_key,
)

FAKE_PDF = b"%PDF-1.4 fake content"


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def json(self):
        return self._body


def _patch_post(monkeypatch, body, status=200):
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs.get("params")
        calls["json"] = kwargs.get("json")
        return FakeResponse(body, status)

    monkeypatch.setattr("finance.pdf2md.requests.post", fake_post)
    return calls


def test_success_returns_text(monkeypatch):
    calls = _patch_post(
        monkeypatch,
        {"candidates": [{"content": {"parts": [{"text": "# Report"}]}}]},
    )
    text = generate_markdown(FAKE_PDF, "secret-key")
    assert text == "# Report"
    assert calls["url"].endswith(f"{DEFAULT_MODEL}:generateContent")
    assert calls["params"] == {"key": "secret-key"}
    parts = calls["json"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "application/pdf"
    assert parts[0]["inline_data"]["data"]


def test_multipart_text_is_joined(monkeypatch):
    _patch_post(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]})
    assert generate_markdown(FAKE_PDF, "k") == "ab"


def test_cp1252_control_punctuation_is_cleaned(monkeypatch):
    _patch_post(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "CFRA\u0092s"}, {"text": " up \u2014 now"}]}}]})
    assert generate_markdown(FAKE_PDF, "k") == "CFRA\u2019s up \u2014 now"


def test_clean_punctuation_passthrough():
    assert clean_punctuation("plain text 123") == "plain text 123"


def test_http_200_with_error_payload_raises(monkeypatch):
    _patch_post(monkeypatch, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid"}})
    with pytest.raises(Pdf2mdError, match="API key not valid"):
        generate_markdown(FAKE_PDF, "bad-key")


def test_model_not_found_hints_at_override(monkeypatch):
    _patch_post(
        monkeypatch,
        {"error": {"code": 404, "message": "models/gemini-9-x is not found for API version v1beta"}},
    )
    with pytest.raises(Pdf2mdError, match="GEMINI_PDF_MODEL"):
        generate_markdown(FAKE_PDF, "k", model="gemini-9-x")


def test_non_200_status_raises(monkeypatch):
    _patch_post(monkeypatch, {"foo": "bar"}, status=429)
    with pytest.raises(Pdf2mdError, match="HTTP 429"):
        generate_markdown(FAKE_PDF, "k")


def test_no_candidates_raises(monkeypatch):
    _patch_post(monkeypatch, {"candidates": []})
    with pytest.raises(Pdf2mdError, match="no candidates"):
        generate_markdown(FAKE_PDF, "k")


def test_empty_response_raises(monkeypatch):
    _patch_post(monkeypatch, {"candidates": [{"content": {"parts": [{"text": "   "}]}}]})
    with pytest.raises(Pdf2mdError, match="empty response"):
        generate_markdown(FAKE_PDF, "k")


def test_empty_pdf_raises(monkeypatch):
    _patch_post(monkeypatch, {})
    with pytest.raises(Pdf2mdError, match="empty"):
        generate_markdown(b"", "k")


def test_oversized_pdf_raises(monkeypatch):
    with pytest.raises(Pdf2mdError, match="limit"):
        generate_markdown(b"x" * (MAX_INLINE_BYTES + 1), "k")


def test_resolve_api_key_requires_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(Pdf2mdError, match="GEMINI_API_KEY"):
        resolve_api_key()


def test_convert_pdf_writes_markdown(tmp_path, monkeypatch):
    pdf = tmp_path / "mu3.pdf"
    pdf.write_bytes(FAKE_PDF)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("finance.pdf2md.generate_markdown", lambda b, k, m: "# Markdown")
    out = convert_pdf(str(pdf))
    assert out.name == "mu3_pdf2md.md"
    assert out.read_text(encoding="utf-8") == "# Markdown"


def test_convert_pdf_custom_output(tmp_path, monkeypatch):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(FAKE_PDF)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("finance.pdf2md.generate_markdown", lambda b, k, m: "# M")
    out = convert_pdf(str(pdf), out_path=str(tmp_path / "parsed.txt"))
    assert out.name == "parsed.md"


def test_convert_pdf_missing_file_raises(tmp_path):
    with pytest.raises(Pdf2mdError, match="not found"):
        convert_pdf(str(tmp_path / "nope.pdf"))


def test_convert_pdf_non_pdf_raises(tmp_path):
    txt = tmp_path / "note.txt"
    txt.write_text("hello")
    monkeypatch_present = pytest.MonkeyPatch()
    with pytest.raises(Pdf2mdError, match="Not a PDF"):
        convert_pdf(str(txt))
    monkeypatch_present.undo()


def test_main_no_args_prints_usage(capsys):
    assert main([]) == 0
    assert "Usage" in capsys.readouterr().out


def test_main_handles_pdf2md_error(capsys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("finance.pdf2md.convert_pdf", lambda *a, **k: (_ for _ in ()).throw(Pdf2mdError("boom")))
    assert main(["missing.pdf", "model-1", "out"]) == 1
    assert "boom" in capsys.readouterr().err


def test_main_prints_heavy_glyphs_without_crash(tmp_path, monkeypatch, capsys):
    dst = tmp_path / "out.md"
    dst.write_text("CFRA \u2605\u2605\u2605\u2605 [could not read]", encoding="utf-8")
    monkeypatch.setattr("finance.pdf2md.convert_pdf", lambda *a, **k: dst)
    assert main(["report.pdf"]) == 0
    out = capsys.readouterr().out
    assert "\u2605" in out
    assert "[could not read]" in out