from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from imga_api.routes.tenant_analyze import _classify_manual_analysis
from imga_api.routes.tenant_intelligence import parse_customer_csv
from imga_api.services.churn_scoring import score_customer
from imga_api.services.company_intelligence import (
    analysis_profile,
    context_directive,
    context_fingerprint,
    structural_findings,
)
from imga_api.services.intelligence_schemas import (
    CompanyContext,
    CustomerProfile,
    PrdDocument,
    ReviewSignals,
)
from imga_api.services.prd_service import interview, starter_document
from imga_api.workers.file_parser import FileParseError, iter_rows
from pydantic import ValidationError

TODAY = datetime.now(UTC).date()
BASE = "/tenants/me/intelligence"


def customer(**kwargs: Any) -> CustomerProfile:
    return CustomerProfile.model_validate(
        {
            "external_id": "0001",
            "name": "Test account",
            "source": "CRM",
            "observed_on": TODAY.isoformat(),
            **kwargs,
        }
    )


def test_churn_insufficient_is_not_zero() -> None:
    result = score_customer(customer(), ReviewSignals(), as_of=TODAY)
    assert result.score is None and result.band == "unknown"
    result = score_customer(
        customer(overdue_invoices=0, cancellation_requested=False), ReviewSignals(), as_of=TODAY
    )
    assert result.score == 0 and result.band == "low"


def test_churn_stale_and_inactive() -> None:
    result = score_customer(
        customer(observed_on=(TODAY - timedelta(days=15)).isoformat(), cancellation_requested=True),
        ReviewSignals(),
        as_of=TODAY,
    )
    assert result.score is None and result.data_status == "stale"
    result = score_customer(
        customer(lifecycle="churned", cancellation_requested=True), ReviewSignals(), as_of=TODAY
    )
    assert result.band == "inactive"


def test_churn_cancellation_caps_and_observation_time() -> None:
    result = score_customer(
        customer(
            cancellation_requested=True,
            overdue_invoices=2,
            orders_current_30d=0,
            orders_previous_30d=20,
            usage_current_30d=0,
            usage_previous_30d=30,
        ),
        ReviewSignals(total=5, negative=5),
        as_of=TODAY,
    )
    assert result.score == 100 and result.band == "critical"
    assert next(s.points for s in result.signals if s.code == "behavior_drop") == 35
    observed = TODAY - timedelta(days=10)
    result = score_customer(
        customer(
            observed_on=observed.isoformat(),
            last_activity_on=observed.isoformat(),
            expected_activity_days=3,
            overdue_invoices=0,
        ),
        ReviewSignals(),
        as_of=TODAY,
    )
    assert not any(s.code == "inactivity" for s in result.signals)


@pytest.mark.parametrize(
    "values",
    [
        {"observed_on": "2099-01-01"},
        {"orders_current_30d": 1},
        {"annual_revenue": "10"},
        {"external_id": "../customer"},
        {"overdue_invoices": -1},
    ],
)
def test_customer_validation(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        customer(**values)


def test_prd_interview_matures_without_fabricating_answers() -> None:
    document = starter_document()
    assert len(document.sections) == 16
    assert interview(document)["is_industry_standard"] is False
    assert interview(document)["questions"][0]["field"] == "answer"
    document.sections[0].answer = "A measured customer problem"
    assert interview(document)["questions"][0]["field"] == "evidence"
    document.sections[0].status = "confirmed"
    with pytest.raises(ValidationError):
        PrdDocument.model_validate(document.model_dump())


def test_company_structure_and_context_version() -> None:
    with pytest.raises(ValidationError):
        CompanyContext.model_validate(
            {
                "units": [
                    {"id": "a", "name": "A", "parent_id": "b"},
                    {"id": "b", "name": "B", "parent_id": "a"},
                ]
            }
        )
    with pytest.raises(ValidationError):
        CompanyContext.model_validate(
            {"processes": [{"id": "p", "name": "P", "owner_unit_id": "missing"}]}
        )
    assert len(structural_findings(CompanyContext())) == 2
    assert analysis_profile({}) == "tr"
    settings = {
        "company_intelligence": {
            "name": "Company",
            "analysis_profile": "mena",
            "report_language": "ar",
        }
    }
    assert analysis_profile(settings) == "mena"
    assert "Modern Standard Arabic" in context_directive(settings)
    assert context_fingerprint(settings) != context_fingerprint({})
    with pytest.raises(ValidationError, match="64 KiB"):
        CompanyContext.model_validate(
            {"units": [{"id": f"u{i}", "name": "Unit", "mandate": "x" * 1000} for i in range(70)]}
        )


def test_csv_preserves_ids_and_rejects_partial_or_duplicate_input() -> None:
    raw = f"external_id,name,source,observed_on\n0001,عميل,CRM,{TODAY}\n".encode()
    assert parse_customer_csv(raw)[0].external_id == "0001"
    for invalid in [
        raw + f"0001,Again,CRM,{TODAY}\n".encode(),
        b"name,source\nX,CRM\n",
        raw + b"broken\n",
    ]:
        with pytest.raises(ValueError):
            parse_customer_csv(invalid)


def test_review_import_identity_is_not_date(tmp_path: Path) -> None:
    path = tmp_path / "reviews.csv"
    path.write_text(
        "yorum,customer_id\nالخدمة سيئة,20260901\nسروس خراب ہے,0002\n", encoding="utf-8"
    )
    rows = list(iter_rows(path, text_column="yorum", source_column=None))
    assert [row.customer_external_id for row in rows] == ["20260901", "0002"]
    assert all(row.review_date is None for row in rows)
    path.write_text("yorum,customer_id,musteri_id\nTest,1,2\n", encoding="utf-8")
    with pytest.raises(FileParseError):
        list(iter_rows(path, text_column="yorum", source_column=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("text,allow", [("الخدمة سيئة", True), ("service bohat kharab hai", False)])
async def test_manual_mena_never_calls_classic(text: str, allow: bool, stub_pipeline: Any) -> None:
    with pytest.raises(HTTPException) as error:
        await _classify_manual_analysis(text, stub_pipeline, None, (), allow_classic=allow)
    assert error.value.status_code == 503


def login(client: TestClient, seed: Any, who: str = "alice", tenant: str = "acme") -> None:
    user = getattr(seed, who)
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": user.email, "password": user.password})
    assert response.status_code == 200, response.text
    response = client.post(
        "/auth/switch-tenant", json={"tenant_id": str(getattr(seed, f"{tenant}_tenant_id"))}
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_documents_roles_versions_and_isolation(
    e2e_client: TestClient, e2e_seed: Any
) -> None:
    client = e2e_client
    login(client, e2e_seed)
    original = client.get(BASE + "/documents/prd").json()
    assert original["revision"] == 0 and len(original["content"]["sections"]) == 16
    body = {"expected_revision": 0, "content": original["content"], "status": "draft"}
    saved = client.put(BASE + "/documents/prd", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert client.put(BASE + "/documents/prd", json=body).status_code == 409
    assert (
        client.put(
            BASE + "/documents/prd", json={**body, "expected_revision": 1, "status": "approved"}
        ).status_code
        == 422
    )
    assert client.get(BASE + "/prd/export").headers["content-type"].startswith("text/markdown")
    company = CompanyContext(name="Acme", analysis_profile="mena", report_language="ar").model_dump(
        mode="json"
    )
    invalid_company = {
        **company,
        "processes": [{"id": "p", "name": "Delivery", "category_codes": ["nonexistent_category"]}],
    }
    invalid = client.put(
        BASE + "/documents/company",
        json={"expected_revision": 0, "status": "approved", "content": invalid_company},
    )
    assert invalid.status_code == 422 and "nonexistent_category" in invalid.text
    assert (
        client.put(
            BASE + "/documents/company",
            json={"expected_revision": 0, "status": "approved", "content": company},
        ).status_code
        == 200
    )
    company["analysis_profile"] = "tr"
    assert (
        client.put(
            BASE + "/documents/company",
            json={"expected_revision": 1, "status": "draft", "content": company},
        ).status_code
        == 200
    )
    diagnostic = client.get(BASE + "/company/diagnostics")
    assert diagnostic.status_code == 200, diagnostic.text
    assert diagnostic.json()["published_revision"] == 1
    assert len(client.get(BASE + "/documents/company/history").json()) == 2
    login(client, e2e_seed, "bob")
    assert (
        client.put(
            BASE + "/documents/company",
            json={"expected_revision": 2, "status": "approved", "content": company},
        ).status_code
        == 403
    )
    login(client, e2e_seed, "bob", "beta")
    assert client.get(BASE + "/documents/company").json()["revision"] == 0
    assert client.put(BASE + "/documents/prd", json=body).status_code == 403
    assert client.get(BASE + "/customers").json()["account_count"] == 0


@pytest.mark.asyncio
async def test_customer_workflow_atomic_import_history_and_erase(
    e2e_client: TestClient, e2e_seed: Any
) -> None:
    client = e2e_client
    login(client, e2e_seed)
    profile = customer(cancellation_requested=True).model_dump(mode="json")
    body = {"expected_revision": 0, "profile": profile}
    response = client.put(BASE + "/customers/0001", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["risk"]["band"] == "critical"
    assert client.put(BASE + "/customers/0001", json=body).status_code == 409
    assert client.get(BASE + "/customers?band=critical").json()["total"] == 1
    assert client.get(BASE + "/customers/0001/history").json()[0]["revision"] == 1
    csv_data = (
        f"external_id,name,source,observed_on\n0002,New,CRM,{TODAY}\n0001,Old,CRM,2020-01-01\n"
    )
    response = client.post(
        BASE + "/customer-import", files={"file": ("customers.csv", csv_data.encode(), "text/csv")}
    )
    assert response.status_code == 409, response.text
    assert client.get(BASE + "/customers").json()["account_count"] == 1
    login(client, e2e_seed, "bob", "beta")
    assert client.get(BASE + "/customers/0001/history").json() == []
    assert client.delete(BASE + "/customers/0001").status_code == 403
    login(client, e2e_seed)
    assert client.delete(BASE + "/customers/0001").status_code == 204
    assert client.get(BASE + "/customers/0001/history").json() == []


@pytest.mark.asyncio
async def test_database_forces_tenant_isolation(e2e_seed: Any) -> None:
    from imga_db import create_engine, create_session_factory
    from imga_db.models import CustomerAccount, CustomerObservation, IntelligenceRevision
    from sqlalchemy import func, select, text
    from sqlalchemy.exc import DBAPIError

    owner = create_engine("admin")
    app = create_engine("app")
    try:
        async with create_session_factory(owner)() as session, session.begin():
            for tenant_id in (e2e_seed.acme_tenant_id, e2e_seed.beta_tenant_id):
                session.add(
                    CustomerAccount(
                        tenant_id=tenant_id,
                        external_id="same-id",
                        revision=1,
                        profile=customer().model_dump(mode="json"),
                    )
                )
                session.add(
                    IntelligenceRevision(
                        tenant_id=tenant_id,
                        kind="prd",
                        revision=1,
                        status="draft",
                        content=starter_document().model_dump(mode="json"),
                    )
                )
                await session.flush()
                session.add(
                    CustomerObservation(
                        tenant_id=tenant_id, external_id="same-id", revision=1, profile={}, risk={}
                    )
                )
        async with create_session_factory(app)() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :id, true)"),
                {"id": str(e2e_seed.acme_tenant_id)},
            )
            for model in (CustomerAccount, CustomerObservation, IntelligenceRevision):
                assert (
                    await session.execute(select(func.count()).select_from(model))
                ).scalar_one() == 1
            states = (
                await session.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN ('customer_accounts','customer_observations','intelligence_revisions')"
                    )
                )
            ).all()
            assert len(states) == 3 and all(rls and force for rls, force in states)
        with pytest.raises(DBAPIError):
            async with create_session_factory(app)() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :id, true)"),
                    {"id": str(e2e_seed.acme_tenant_id)},
                )
                session.add(
                    CustomerAccount(
                        tenant_id=e2e_seed.beta_tenant_id,
                        external_id="forbidden",
                        revision=1,
                        profile={},
                    )
                )
                await session.flush()
    finally:
        await owner.dispose()
        await app.dispose()


@pytest.mark.asyncio
async def test_3000_customer_csv_import(e2e_client: TestClient, e2e_seed: Any) -> None:
    login(e2e_client, e2e_seed)
    data = "external_id,name,source,observed_on\n" + "\n".join(
        f"c{i:05},Customer {i},CRM,{TODAY}" for i in range(3000)
    )
    response = e2e_client.post(
        BASE + "/customer-import", files={"file": ("customers.csv", data.encode(), "text/csv")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 3000
    result = e2e_client.get(BASE + "/customers?page=120").json()
    assert result["account_count"] == 3000 and len(result["items"]) == 25
    assert result["counts"]["unknown"] == 3000
    update = f"external_id,name,source,observed_on,cancellation_requested\nc00000,Customer 0,CRM,{TODAY},true\n"
    assert (
        e2e_client.post(
            BASE + "/customer-import",
            files={"file": ("customers.csv", update.encode(), "text/csv")},
        ).status_code
        == 200
    )
    history = e2e_client.get(BASE + "/customers/c00000/history").json()
    assert [row["revision"] for row in history] == [2, 1]
    assert history[0]["risk"]["band"] == "critical"


@pytest.mark.asyncio
async def test_manual_and_batch_build_published_mena_context(
    e2e_seed: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from imga_api.routes.tenant_analyze import _build_manual_unified_context
    from imga_api.services import llm_credentials
    from imga_api.services.llm_credentials import LlmKeySelection
    from imga_api.workers.batch_analyzer import _build_unified_context
    from imga_core.llm.key_rotation import GeminiKey
    from imga_db import create_engine, create_session_factory, set_current_tenant
    from imga_db.models import Tenant

    async def keys(*args: Any) -> LlmKeySelection:
        return LlmKeySelection(
            provider="gemini",
            model="test",
            keys=[GeminiKey(id="test", value="not-a-key", label="test", priority=1)],
        )

    monkeypatch.setattr(llm_credentials, "load_active_llm_keys", keys)
    engine = create_engine("admin")
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            tenant = await session.get(Tenant, e2e_seed.acme_tenant_id)
            assert tenant is not None
            tenant.settings = {"company_intelligence": {"analysis_profile": "mena"}}
        context = SimpleNamespace(
            admin_session_factory=factory, settings=SimpleNamespace(llm_concurrency=6)
        )
        batch = await _build_unified_context(e2e_seed.acme_tenant_id, context)
        assert batch is not None and batch.engine.analysis_profile == "mena"
        async with factory() as session, session.begin():
            await set_current_tenant(session, e2e_seed.acme_tenant_id)
            manual = await _build_manual_unified_context(session, e2e_seed.acme_tenant_id)
            assert manual is not None and manual.engine.analysis_profile == "mena"
    finally:
        await engine.dispose()
