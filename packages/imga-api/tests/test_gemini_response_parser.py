"""Sprint 8.3.11 — Gemini structured-response parser regression tests.

The /executive-briefing browser smoke fail in Sprint 8.3.10 deploy
was a non-JSON parse error: Gemini Flash sometimes wraps the body
in a ``​```json ... ​``` `` fence even when ``response_mime_type=
application/json`` is requested. The parser now strips fences +
falls back to outermost-{...} extraction before raising.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from imga_core.llm.errors import MalformedResponseError
from imga_core.llm.gemini import GeminiProvider, _strip_markdown_fences


def _resp(text: str) -> SimpleNamespace:
    """Mimic the Gemini SDK response object's ``.text`` attribute
    without importing the SDK."""
    return SimpleNamespace(text=text)


def test_strip_markdown_fences_handles_json_tag() -> None:
    assert (
        _strip_markdown_fences('```json\n{"a": 1}\n```')
        == '{"a": 1}'
    )


def test_strip_markdown_fences_handles_bare_fence() -> None:
    assert (
        _strip_markdown_fences("```\n{\"a\": 1}\n```")
        == '{"a": 1}'
    )


def test_strip_markdown_fences_passthrough_on_clean_input() -> None:
    """No fences → no-op. The cleaner only fires when both an open
    and close fence are present."""
    assert _strip_markdown_fences('{"a": 1}') == '{"a": 1}'


def test_strip_markdown_fences_ignores_orphan_open() -> None:
    """A leading ``​```​`` without a matching close is left alone so
    we don't accidentally turn malformed input into "valid" JSON."""
    text = "```\n{not json"
    assert _strip_markdown_fences(text) == text


def test_parse_structured_response_unwraps_markdown() -> None:
    """Gemini Flash regression: payload arrived inside a json
    fence; parser must unwrap before json.loads."""
    raw = '```json\n{"headline": "test", "kpi_changes": []}\n```'
    parsed = GeminiProvider._parse_structured_response(_resp(raw))
    assert parsed == {"headline": "test", "kpi_changes": []}


def test_parse_structured_response_clean_json() -> None:
    raw = '{"headline": "test", "kpi_changes": []}'
    parsed = GeminiProvider._parse_structured_response(_resp(raw))
    assert parsed["headline"] == "test"


def test_parse_structured_response_extracts_outermost_object() -> None:
    """Defensive fallback: stray prose around a JSON object still
    parses via the find-{ … find-} slice."""
    raw = (
        "Here is your briefing:\n"
        '{"headline": "ok", "kpi_changes": []}\n'
        "Hope this helps!"
    )
    parsed = GeminiProvider._parse_structured_response(_resp(raw))
    assert parsed["headline"] == "ok"


def test_parse_structured_response_raises_on_truly_unparseable() -> None:
    """Non-JSON garbage with no recognisable object must still
    raise MalformedResponseError; the fallback is for surrounding
    prose, not for arbitrary text."""
    raw = "This is just words, no JSON at all."
    with pytest.raises(MalformedResponseError, match="non-JSON text"):
        GeminiProvider._parse_structured_response(_resp(raw))


def test_parse_structured_response_rejects_array_root() -> None:
    """The top-level must be an object — arrays surface as
    MalformedResponseError so the service layer doesn't try to
    treat them as a dict."""
    raw = "[1, 2, 3]"
    with pytest.raises(MalformedResponseError, match="Expected JSON object"):
        GeminiProvider._parse_structured_response(_resp(raw))
