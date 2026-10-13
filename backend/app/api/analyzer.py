from __future__ import annotations

import re
import uuid
from typing import Any

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession, OptionalUser
from app.core.errors import Forbidden, NotFound, Unprocessable
from app.core.ratelimit import expensive_limit
from app.domain.enums import AnalysisInput
from app.models import AnalysisRun
from app.schemas.api import AnalyzeTextIn, AnalyzeUrlIn
from app.services.analyzer.documents import extract_text
from app.services.analyzer.pipeline import analyze
from app.services.safe_fetch import EgressDenied, FetchError, fetch
from app.services.sources.base import retrying_fetch
from app.services.sources.event_pages import extract_open_graph
from app.services.urls import canonicalize_url

router = APIRouter(prefix="/api/analyzer", tags=["analyzer"], dependencies=[Depends(expensive_limit)])
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


def html_to_text(html: str) -> tuple[str, str | None, str | None]:
    """Return (readable text, title, canonical link). Script/style/nav content is dropped."""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else None
    canon_tag = soup.find("link", rel="canonical")
    canon = canon_tag.get("href") if canon_tag and canon_tag.get("href") else None
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "iframe", "template"]):
        t.decompose()
    for c in soup.find_all(string=lambda s: s.__class__.__name__ == "Comment"):
        c.extract()
    text = soup.get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()
    return text, title, canon  # type: ignore[return-value]


@router.post("/text")
def analyze_text(body: AnalyzeTextIn, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    return analyze(db, text=body.text, input_type=AnalysisInput.TEXT, actor=user, persist_claims=False)


@router.post("/url")
def analyze_url(body: AnalyzeUrlIn, db: DbSession, user: OptionalUser) -> dict[str, Any]:
    if canonicalize_url(body.url) is None:
        raise Unprocessable("That does not look like a valid http(s) URL.", code="invalid_url")
    try:
        doc = retrying_fetch(lambda: fetch(body.url, allowed_types=HTML_TYPES, respect_robots=True, max_bytes=3_000_000))
    except EgressDenied as exc:
        raise Unprocessable(
            "This deployment's network policy does not allow retrieving that site, so the page could not be read. "
            "Paste the event text into the analyzer instead, or ask the organizer to submit the page through their dashboard.",
            code="egress_denied", details=[exc.message],
        ) from exc
    except FetchError as exc:
        raise Unprocessable(f"The page could not be retrieved: {exc.message}", code=exc.code) from exc
    text, title, canon = html_to_text(doc.text)
    og = extract_open_graph(doc.text)
    pieces = [p for p in (title or og.get("og:title"), og.get("og:description"), text) if p]
    combined = "\n\n".join(dict.fromkeys(pieces))
    if len(combined.strip()) < 40:
        raise Unprocessable("The page was retrieved but contained too little readable text (it may render with JavaScript).", code="no_readable_text")
    canonical = canonicalize_url(canon or doc.final_url) or doc.final_url
    result = analyze(db, text=combined, input_type=AnalysisInput.URL, actor=user, persist_claims=False, source_url=doc.final_url,
                     canonical_url=canon or doc.final_url, source_label=f"the page at {canonical}")
    result["retrieval"] = {"requested_url": body.url, "final_url": doc.final_url, "canonical_url": canon or doc.final_url,
                           "retrieved_at": doc.fetched_at.isoformat(), "content_type": doc.content_type, "title": title}
    return result


@router.post("/file")
async def analyze_file(db: DbSession, user: OptionalUser, file: UploadFile = File(...)) -> dict[str, Any]:
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    doc = extract_text(data, file.filename or "upload", limit)
    result = analyze(db, text=doc.text, input_type=AnalysisInput.FILE, actor=user, persist_claims=False, file_name=(file.filename or "upload")[:300],
                     extra_notes=doc.notes, source_label=f"the uploaded file ({doc.method.replace('_', ' ')})")
    result["document"] = {"file_name": file.filename, "method": doc.method, "mime": doc.mime, "sha256": doc.sha256, "characters": len(doc.text)}
    return result


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise NotFound("Analysis not found.")
    if run.created_by != user.id and user.role not in ("admin", "reviewer"):
        raise Forbidden("You can only open your own analyses.", code="not_yours")
    return {"id": str(run.id), "created_at": run.created_at.isoformat(), "input_type": run.input_type, "provider": run.provider,
            "model": run.model, "used_fallback": run.used_fallback, "injection_flags": run.injection_flags, "result": run.result}


@router.get("/runs")
def my_runs(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    rows = db.scalars(select(AnalysisRun).where(AnalysisRun.created_by == user.id).order_by(AnalysisRun.created_at.desc()).limit(30))
    return {"items": [{"id": str(r.id), "created_at": r.created_at.isoformat(), "input_type": r.input_type, "provider": r.provider,
                       "used_fallback": r.used_fallback, "summary": (r.result or {}).get("summary"), "file_name": r.file_name,
                       "source_url": r.source_url, "event_id": str(r.event_id) if r.event_id else None} for r in rows]}
