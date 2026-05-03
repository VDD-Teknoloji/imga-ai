"""Coverage for the optional ``nps_score`` field on POST /tenants/me/analyze.

Sprint 8.3.5. Three thin tests against the live route + real DB:

  * Field present + in range → Review.nps_score persisted, nps_category
    computed via the Postgres GENERATED column.
  * Field omitted → Review.nps_score NULL (not 0, not crash). Existing
    callers that don't carry NPS keep working untouched.
  * Field out of range → 422 at the Pydantic layer (``ge=0, le=10``).
    The DB check constraint is the second line of defense; this test
    pins the friendlier 422 path so a regression to 500 is loud.

Uses the shared ``batch_client`` fixture so the lifespan-built pipeline
(stub, deterministic) runs the analyze pass and ReviewService records.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from imga_db.models import Review, User
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.batch_helpers import login_token


@pytest.mark.asyncio
async def test_analyze_persists_optional_nps_score(
    batch_client: TestClient,
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Kargom dün geldi", "nps_score": 9},
    )
    assert r.status_code == 200, r.text
    review_id = r.json()["review_id"]

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        review = (
            await admin_session.execute(
                select(Review).where(Review.id == UUID(review_id))
            )
        ).scalar_one()
    assert review.nps_score == 9
    # The GENERATED column should bucket 9 → promoter automatically.
    assert review.nps_category == "promoter"


@pytest.mark.asyncio
async def test_analyze_omitting_nps_score_persists_null(
    batch_client: TestClient,
    admin_session: AsyncSession,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Kargom dün geldi"},
    )
    assert r.status_code == 200, r.text
    review_id = r.json()["review_id"]

    async with admin_session.begin():
        await admin_session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": str(tid)},
        )
        review = (
            await admin_session.execute(
                select(Review).where(Review.id == UUID(review_id))
            )
        ).scalar_one()
    assert review.nps_score is None
    assert review.nps_category is None


@pytest.mark.asyncio
async def test_analyze_rejects_out_of_range_nps_at_request_validation(
    batch_client: TestClient,
    manual_tenant: tuple[User, UUID, str],
) -> None:
    """The Pydantic ``ge=0, le=10`` guard fires before the route body
    runs — a friendlier 422 than letting the DB check constraint fail
    inside record_and_decide and turn into a 500."""
    user, tid, pw = manual_tenant
    token = login_token(batch_client, user.email, pw, tid)

    r = batch_client.post(
        "/tenants/me/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={"text": "Kargom dün geldi", "nps_score": 15},
    )
    assert r.status_code == 422, r.text
