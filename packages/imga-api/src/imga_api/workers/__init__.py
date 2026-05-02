"""Async background workers (APScheduler-driven).

Sprint 8.3.1 — batch CSV/XLSX upload analyzer + daily upload reaper.
Workers run in-process inside the FastAPI app; the lifespan starts /
stops the AsyncIOScheduler.
"""
