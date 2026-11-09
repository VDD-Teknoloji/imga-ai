"""Marketing demo adapters over the application's Twitter services."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from imga_api.db_deps import get_admin_session
from imga_api.services.llm_credentials import NoCredentialsError
from imga_api.services.trial_analysis_service import TRIAL_TENANT_ID
from imga_api.services.twitter_brand_service import (
    BrandPlanError,
    compose_term,
    judge_tweet_relevance,
    normalize_handle,
    plan_brand_search,
)
from imga_api.services.twitter_import import (
    TwitterFetchError,
    build_search_query,
    fetch_tweets,
    parse_search_terms,
)

router = APIRouter(prefix="/twitter")


class PlanInput(BaseModel):
    brand: str = Field(min_length=2, max_length=120)
    handle: str | None = Field(default=None, max_length=50)


class SearchInput(PlanInput):
    term: str = Field(min_length=2, max_length=400)
    count: int = Field(default=100, ge=10, le=100)
    brand_summary: str | None = Field(default=None, max_length=1000)
    relevance_check: bool = True


async def bind_trial(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
        {"tenant": str(TRIAL_TENANT_ID)},
    )


@router.post("/plan")
async def plan(
    body: PlanInput, session: Annotated[AsyncSession, Depends(get_admin_session)]
) -> dict[str, Any]:
    await bind_trial(session)
    try:
        async with asyncio.timeout(60):
            result = await plan_brand_search(
                session,
                TRIAL_TENANT_ID,
                brand=body.brand.strip(),
                handle=body.handle,
                actor_user_id=None,
            )
    except NoCredentialsError as exc:
        raise HTTPException(503, "planning_unavailable") from exc
    except (BrandPlanError, TimeoutError) as exc:
        raise HTTPException(502, "planning_failed") from exc
    term = compose_term(result.include, result.exclude)
    return {
        **asdict(result),
        "term": term,
        "query_preview": build_search_query(term, result.handle),
    }


@router.post("/preview")
async def preview(body: SearchInput) -> dict[str, str]:
    terms = parse_search_terms(body.term)
    if not terms.positive:
        raise HTTPException(422, "invalid_terms")
    return {"query_preview": build_search_query(body.term, normalize_handle(body.handle))}


@router.post("/fetch")
async def fetch(
    body: SearchInput,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_admin_session)],
) -> dict[str, Any]:
    key = request.app.state.settings.twitterapi_io_key
    if not key:
        raise HTTPException(503, "twitter_unavailable")
    terms = parse_search_terms(body.term)
    if not terms.positive:
        raise HTTPException(422, "invalid_terms")
    handle = normalize_handle(body.handle)
    await bind_trial(session)
    try:
        async with asyncio.timeout(150):
            result = await fetch_tweets(
                api_key=key,
                term=body.term,
                count=body.count,
                exclude_handle=handle,
                max_pages=20,
            )
            kept = result.tweets
            skipped = False
            filtered_by_ai = 0
            if body.relevance_check and kept:
                try:
                    verdict = await judge_tweet_relevance(
                        session,
                        TRIAL_TENANT_ID,
                        brand=body.brand,
                        brand_summary=body.brand_summary,
                        include=list(terms.positive),
                        exclude=list(terms.negative),
                        handle=handle,
                        tweets=[tweet.raw_text or tweet.text for tweet in kept],
                        actor_user_id=None,
                    )
                    kept = [
                        tweet
                        for tweet, relevant in zip(kept, verdict.relevant, strict=True)
                        if relevant
                    ]
                    filtered_by_ai = verdict.dropped
                    skipped = verdict.failed_batches > 0
                except NoCredentialsError:
                    skipped = True
    except TwitterFetchError as exc:
        raise HTTPException(502, "twitter_failed") from exc
    except TimeoutError as exc:
        raise HTTPException(504, "twitter_timeout") from exc
    return {
        "texts": [tweet.text for tweet in kept],
        "details": {
            "brand": body.brand,
            "brand_summary": body.brand_summary,
            "term": body.term,
            "handle": handle,
            "query": build_search_query(body.term, handle),
            "requested": body.count,
            "fetched_total": result.fetched_total,
            "pages": result.pages,
            "filtered_out": result.filtered_out,
            "excluded_collab": result.excluded_collab,
            "filtered_by_ai": filtered_by_ai,
            "relevance_check": body.relevance_check,
            "ai_check_skipped": skipped,
            "kept": len(kept),
            "exhausted": result.exhausted,
            "oldest_tweet_at": result.oldest_tweet_at,
            "newest_tweet_at": result.newest_tweet_at,
            # Match the application's privacy policy: no author identities or raw text.
            "tweets": [
                {
                    "text": tweet.text,
                    "url": tweet.url,
                    "created_at": tweet.created_at,
                    "like_count": tweet.like_count,
                    "retweet_count": tweet.retweet_count,
                    "reply_count": tweet.reply_count,
                    "view_count": tweet.view_count,
                }
                for tweet in kept
            ],
        },
    }
