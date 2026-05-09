"""Sprint 9.3 D — PromptResolver pure-render tests.

The DB-bound resolution chain (tenant override → global → None) is
covered by a separate integration test that talks to the test
postgres; this file exercises the pure ``_render_row`` helper +
``MissingRequiredVariable`` path so future refactors of the Jinja2
plumbing can't regress the contract."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from imga_api.services.prompt_resolver import (
    MissingRequiredVariable,
    PromptResolverError,
    _render_row,
)


class _FakeTemplate:
    """Stand-in for the SQLAlchemy ``PromptTemplate`` row — only
    the fields ``_render_row`` reads."""

    def __init__(
        self,
        *,
        template_key: str = "classification",
        version: str = "v1",
        tenant_id=None,
        system_prompt: str = "You are a helpful classifier.",
        user_prompt_template: str = "Classify: {{ text }}",
        required_variables: list[str] | None = None,
        response_schema: dict | None = None,
    ) -> None:
        self.template_key = template_key
        self.version = version
        self.tenant_id = tenant_id
        self.system_prompt = system_prompt
        self.user_prompt_template = user_prompt_template
        self.required_variables = required_variables or []
        self.response_schema = response_schema or {}
        self.model_name = "gemini-2.5-flash"
        self.temperature = 0.1
        self.top_p = 0.9
        self.max_output_tokens = 8192
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)


def test_render_row_substitutes_jinja_variables() -> None:
    template = _FakeTemplate(
        user_prompt_template="Classify the following: {{ text }}",
        required_variables=["text"],
    )
    result = _render_row(template, variables={"text": "merhaba"})
    assert result.user_prompt_rendered == "Classify the following: merhaba"
    assert result.template_key == "classification"
    assert result.version == "v1"
    assert result.source == "global_default"  # no tenant_id set


def test_render_row_marks_tenant_override_source() -> None:
    template = _FakeTemplate(
        tenant_id=uuid4(),
        user_prompt_template="x",
    )
    result = _render_row(template, variables={})
    assert result.source == "tenant_override"


def test_render_row_raises_on_missing_required_variable() -> None:
    template = _FakeTemplate(
        user_prompt_template="Hi {{ name }}",
        required_variables=["name", "topic"],
    )
    with pytest.raises(MissingRequiredVariable, match="topic"):
        _render_row(template, variables={"name": "Alice"})


def test_render_row_raises_on_template_syntax_error() -> None:
    template = _FakeTemplate(
        user_prompt_template="{% for x in items %}{{ x }",  # unterminated tag
    )
    with pytest.raises(PromptResolverError, match="render failed"):
        _render_row(template, variables={"items": []})


def test_render_row_extra_variables_are_ignored() -> None:
    """A variable not referenced by the template is harmless —
    extra entries in the input dict shouldn't make the render
    fail."""
    template = _FakeTemplate(
        user_prompt_template="Just text",
        required_variables=[],
    )
    result = _render_row(
        template,
        variables={"unused": "value", "another": 42},
    )
    assert result.user_prompt_rendered == "Just text"
