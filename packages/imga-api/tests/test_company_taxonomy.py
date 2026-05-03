"""Coverage for the company-perspective taxonomy (Sprint 8.3.5.5).

Three surfaces:

  * imga-core.categorizers.company_heuristic.apply_company_heuristic —
    pure function, no DB. Confidence model: 0.5 base, 1.2x per matched
    keyword, capped at 1.0; ties resolve by priority (lower wins);
    empty taxonomy / no matches → None.
  * /tenants/me/taxonomies — read-only list, ordered by priority,
    RLS-bound. New tenants come up with the 21 default rows.
  * Migration 0017 backfill — every existing tenant landed via
    semi_auto_tenant inherits the 21 default rows from the upgrade
    path's INSERT loop.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_core.categorizers import (
    CompanyHeuristicHit,
    apply_company_heuristic,
)
from imga_db.models import CategoryTaxonomy, User
from imga_db.seeds import DEFAULT_COMPANY_TAXONOMY
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import (
    cleanup_tenant,
    login_token,
    seed_tenant_with_admin,
)

# ---- Heuristic unit (no DB) -------------------------------------


def test_heuristic_returns_none_for_empty_taxonomy() -> None:
    result = apply_company_heuristic("kargom gelmedi", taxonomy=[])
    assert result is None


def test_heuristic_returns_none_when_no_keyword_matches() -> None:
    """Taxonomy non-empty but text doesn't contain any keyword."""
    taxonomy = [
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": ["kargom nerede", "ulaşmadı"],
            "priority": 1,
        }
    ]
    result = apply_company_heuristic(
        "ürün çok güzel teşekkürler", taxonomy=taxonomy
    )
    assert result is None


def test_heuristic_single_keyword_match_yields_boosted_confidence() -> None:
    """Spec-pinned: 0.5 base * 1.2 boost = 0.6 confidence on a single
    keyword match."""
    taxonomy = [
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": ["gelmedi"],
            "priority": 1,
        }
    ]
    hit = apply_company_heuristic("kargom dün gelmedi", taxonomy=taxonomy)
    assert isinstance(hit, CompanyHeuristicHit)
    assert hit.code == "shipment_not_arrived"
    assert hit.confidence == 0.6
    assert hit.matched_keywords == ["gelmedi"]


def test_heuristic_multiple_matches_compound_with_cap() -> None:
    """Each additional matched keyword multiplies confidence by 1.2x;
    the cap is 1.0 so saturation around the fifth match is fine."""
    taxonomy = [
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": [
                "kargom nerede", "gelmedi", "teslim edilmedi",
                "ulaşmadı", "gecikti", "teslimat sorunu",
            ],
            "priority": 1,
        }
    ]
    text_in = (
        "kargom nerede, gelmedi, teslim edilmedi ve ulaşmadı, gecikti — "
        "her şey teslimat sorunu"
    )
    hit = apply_company_heuristic(text_in, taxonomy=taxonomy)
    assert hit is not None
    assert hit.confidence == 1.0  # capped


def test_heuristic_priority_breaks_tie_on_equal_confidence() -> None:
    """Two entries with single-keyword matches both score 0.6; the
    lower-priority number wins (legacy if-elif precedence)."""
    taxonomy = [
        {
            "code": "store_issues",
            "label_tr": "Mağaza Sorunları",
            "keywords": ["personel"],
            "priority": 21,
        },
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": ["personel"],  # contrived: same keyword
            "priority": 1,
        },
    ]
    hit = apply_company_heuristic("personel kötüydü", taxonomy=taxonomy)
    assert hit is not None
    assert hit.code == "shipment_not_arrived"
    assert hit.confidence == 0.6


def test_heuristic_skips_empty_keyword_list() -> None:
    """The default seed's `general_other` fallback ships with empty
    keywords. It must never win the heuristic — empty keyword list →
    skipped."""
    taxonomy = [
        {
            "code": "general_other",
            "label_tr": "Genel ve Diğer Sorunlar",
            "keywords": [],
            "priority": 999,
        },
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": ["gelmedi"],
            "priority": 1,
        },
    ]
    hit = apply_company_heuristic("kargom gelmedi", taxonomy=taxonomy)
    assert hit is not None
    assert hit.code == "shipment_not_arrived"


def test_heuristic_normalize_turkish_match_case_insensitive() -> None:
    """Keyword matching folds through normalize_turkish — uppercase
    İ and dotted/dotless i variants all collapse before comparison."""
    taxonomy = [
        {
            "code": "shipment_not_arrived",
            "label_tr": "Kargom ulaşmadı",
            "keywords": ["ulaşmadı"],
            "priority": 1,
        }
    ]
    hit = apply_company_heuristic("Kargom ULAŞMADI", taxonomy=taxonomy)
    assert hit is not None
    assert hit.code == "shipment_not_arrived"


# ---- Default seed contract ---------------------------------------


def test_default_taxonomy_module_export_has_21_entries() -> None:
    """The user explicitly asked for 21 categories (legacy 23 with #9
    and #10 dropped). Pin it so a future add/remove from the seed
    surfaces in review rather than silently shipping."""
    assert len(DEFAULT_COMPANY_TAXONOMY) == 21


def test_default_taxonomy_codes_are_unique_ascii_snake_case() -> None:
    """Codes must be ASCII (no Türkçe characters) and unique. Label_tr
    keeps the original Türkçe; only code is snake_case."""
    codes = [e["code"] for e in DEFAULT_COMPANY_TAXONOMY]
    assert len(set(codes)) == 21, "duplicate codes in seed"
    for c in codes:
        assert c == c.lower(), f"code {c!r} not lowercase"
        assert c.isascii(), f"code {c!r} contains non-ASCII"
        assert " " not in c, f"code {c!r} contains whitespace"


def test_default_taxonomy_general_other_fallback_has_empty_keywords() -> None:
    """The 21st entry is the legacy fallback — no keywords, lowest
    priority. Pins the contract that the heuristic safely skips it."""
    fallback = next(
        (e for e in DEFAULT_COMPANY_TAXONOMY if e["code"] == "general_other"),
        None,
    )
    assert fallback is not None
    assert fallback["keywords"] == []
    assert fallback["priority"] == 999


# ---- API + DB integration ---------------------------------------


@pytest.mark.asyncio
async def test_existing_tenant_inherits_21_default_rows_via_backfill(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenants seeded by the test fixture (post-migration-0017) must
    have all 21 default taxonomy rows. Migration 0017's data backfill
    is the path that delivers this for prod tenants too."""
    _user, tid, _pw = semi_auto_tenant
    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        rows = (
            await admin_session.execute(
                select(CategoryTaxonomy).where(CategoryTaxonomy.tenant_id == tid)
            )
        ).scalars().all()
    assert len(rows) == 21
    codes = {r.code for r in rows}
    assert "shipment_not_arrived" in codes
    assert "general_other" in codes


@pytest.mark.asyncio
async def test_get_taxonomies_endpoint_returns_seeded_rows_ordered(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
) -> None:
    """The read endpoint sorts by priority (lower first), so
    'shipment_not_arrived' (priority 1) leads and 'general_other'
    (priority 999) trails."""
    user, tid, pw = semi_auto_tenant
    token = login_token(batch_client, user.email, pw, tid)
    r = batch_client.get(
        "/tenants/me/taxonomies",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 21
    assert body[0]["code"] == "shipment_not_arrived"
    assert body[-1]["code"] == "general_other"
    # is_default_seed flag is True on every row out of seed.
    assert all(row["is_default_seed"] for row in body)


@pytest.mark.asyncio
async def test_taxonomies_endpoint_rls_isolates_tenants(
    batch_client: TestClient,
    semi_auto_tenant: tuple[User, UUID, str],
    admin_session: AsyncSession,
) -> None:
    """Tenant B should see its own 21 default rows — not tenant A's,
    not the union. RLS+FORCE on category_taxonomies is the contract."""
    _user_a, _tid_a, _pw_a = semi_auto_tenant
    user_b, tid_b, pw_b = await seed_tenant_with_admin(
        admin_session, name_prefix="Tax Beta"
    )
    try:
        token_b = login_token(batch_client, user_b.email, pw_b, tid_b)
        r = batch_client.get(
            "/tenants/me/taxonomies",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 200
        body = r.json()
        # Tenant B sees its own 21 (seeded by TenantService.create); not
        # tenant A's. Compare row count, not contents — both seed the
        # same defaults but different rows.
        assert len(body) == 21
    finally:
        await cleanup_tenant(admin_session, user_b.id, tid_b)
