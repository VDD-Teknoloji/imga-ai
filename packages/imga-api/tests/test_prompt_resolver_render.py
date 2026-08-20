"""Sprint 9.3 D — PromptResolver pure-render tests.

The DB-bound resolution chain (tenant override → global → None) is
covered by a separate integration test that talks to the test
postgres; this file exercises the pure ``_render_row`` helper +
``MissingRequiredVariable`` path so future refactors of the Jinja2
plumbing can't regress the contract."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from imga_db.models import User

from imga_api.services.prompt_resolver import (
    MissingRequiredVariable,
    PromptResolverError,
    _render_row,
)
from tests.batch_helpers import login_token


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


# ---------------------------------------------------------------------------
# B8 (süper-admin denetim raporu) — katalog tamlığı + whitelist 422
#
# B1 root_cause/quality_report/onboarding_suggest'i select_prompt()'a
# bağladıktan sonra, bu üçü artık ``tenant_prompt_templates.py``'nin
# kataloğunda (``_build_code_defaults``) da görünmeli — aksi halde
# /settings/prompts sayfası bunları hiç listelemez. Whitelist testleri
# B1'in "sessiz tuzak" yarısını kapatır: kataloğun dışında bir
# template_key artık POST'ta 422 döner (öncesinde herhangi bir string
# kabul ediliyordu ve satır hiçbir select_prompt() çağrısı tarafından
# asla okunmuyordu).
# ---------------------------------------------------------------------------


def test_build_code_defaults_has_seven_keys() -> None:
    """root_cause/quality_report/onboarding_suggest B8 ile kataloğa
    eklendi — orijinal dört (swot/okr/briefing/unified_classifier) ile
    birlikte tam yedi anahtar olmalı."""
    from imga_api.routes.tenant_prompt_templates import _build_code_defaults

    keys = {t.template_key for t in _build_code_defaults()}
    assert keys == {
        "swot",
        "okr",
        "briefing",
        "unified_classifier",
        "root_cause",
        "quality_report",
        "onboarding_suggest",
    }


@pytest.mark.asyncio
async def test_create_override_rejects_unknown_template_key(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Kataloğun dışında bir template_key POST'ta 422 döner; mesaj
    geçerli anahtarları da listeler."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/prompt-templates",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "template_key": "uydurma_anahtar",
            "system_prompt": "test",
            "user_prompt_template": "test",
        },
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "bilinmeyen şablon anahtarı" in detail
    assert "root_cause" in detail


@pytest.mark.asyncio
async def test_create_override_accepts_catalog_key(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """Whitelist'in pozitif yarısı: B8'de kataloğa eklenen yeni bir
    anahtar (root_cause) POST'u başarıyla geçmeli — 422 kapısı yalnız
    KATALOG DIŞI anahtarları reddeder."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.post(
        "/tenants/me/prompt-templates",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "template_key": "root_cause",
            "system_prompt": "test system",
            "user_prompt_template": "test user {{ primary_category_label }}",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["template_key"] == "root_cause"
