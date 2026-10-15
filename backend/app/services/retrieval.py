"""The governed retrieval pipeline. ORDER IS A HARD INVARIANT (asserted by tests):

1. hybrid search over-fetch (`ASK_TOP_K * ASK_OVERFETCH_FACTOR` chunks, `repo.search_chunks`)
2. group hits by page -> one `DocumentAccessContext` per page
3. `access_policy.filter` -> denied pages are DROPPED here, before anything else (freshness
   probes, sanitizer, composer, LLM) ever sees them; decisions are kept for the audit only
4. freshness receipt over the allowed pages (`freshness_receipt`, live-verifying critical
   evidence when `FRESHNESS_LIVE_VERIFY_CRITICAL`); unsafe items (and, with `require_fresh`,
   anything not `fresh`) are dropped
5. evidence spans E1..En by rank -> `sanitize` -> `compose` -> `verify` -> `should_abstain`
6. persist the `QueryRecord`, append the `ask` audit event, return the `AnswerEnvelope`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from access_control import AccessSummary, FilterResult, Principal
from freshness import (
    ConnectorKind,
    EvidenceClass,
    EvidenceRef,
    FreshnessReceipt,
    FreshnessStatus,
    ProviderProbe,
    ReceiptRequest,
)
from groundedness import (
    ABSTAIN_ANSWER_TEXT,
    GROUND_ID,
    EvidenceSpan,
    GroundingReport,
    SanitizedEvidence,
    needs_partial_selection,
    procedure_requested,
    select_supported_relevant_claims,
)

from app.connectors.registry import get_connector
from app.core.context import get_request_id
from app.schemas.ask import (
    AnswerEnvelope,
    AnswerOut,
    CitationOut,
    EvidenceBundle,
    EvidenceSpanOut,
    Timing,
)
from app.schemas.domain import Page, QueryRecord, SearchHit, new_id, utcnow
from app.services import audit
from app.services.access import filter_pages
from app.services.compose import MODEL_COMPOSER_ID
from app.services.ingestion import embed_texts

if TYPE_CHECKING:
    from app.services.wiring import Services


def _ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _partial_notice(question: str) -> str:
    if procedure_requested(question):
        return (
            "I could verify the cited facts, but no additional procedure steps "
            "were verified from the available evidence."
        )
    return (
        "I could verify the cited details, but not the rest of the request "
        "from the available evidence."
    )


def _grounding_summary(report: GroundingReport) -> dict[str, Any]:
    return {
        "claims_total": report.claims_total,
        "supported": report.supported,
        "partially_supported": report.partially_supported,
        "unsupported": report.unsupported,
        "contradicted": report.contradicted,
        "coverage_ratio": report.coverage_ratio,
        "report_hash": report.report_hash,
    }


@dataclass
class GovernedEvidence:
    """Everything the pipeline knows after steps 1-5a (sanitize), for ask/assemble_evidence."""

    hits: list[SearchHit]
    retrieved: list[Page]
    filter_result: FilterResult
    allowed: list[Page]
    receipt: FreshnessReceipt
    usable_page_ids: set[str]
    spans: list[EvidenceSpan]
    sanitized: list[SanitizedEvidence]
    timing: dict[str, int] = field(default_factory=dict)
    evaluated_at: Any = None


async def _search(
    services: Services, query: str, *, limit: int, source_ids: list[str] | None
) -> list[SearchHit]:
    vectors = await embed_texts(services, [query])
    embedding = vectors[0] if vectors else None
    return await services.repo.search_chunks(query, embedding, limit=limit, source_ids=source_ids)


async def _pages_in_rank_order(services: Services, hits: list[SearchHit]) -> list[Page]:
    order: list[str] = []
    for hit in hits:
        if hit.page_id not in order:
            order.append(hit.page_id)
    found = await services.repo.get_pages(order)
    return [found[pid] for pid in order if pid in found and found[pid].deleted_at is None]


def _probe_for(services: Services, sources: dict[str, Any]):  # type: ignore[no-untyped-def]
    """`ProbeFor`: the source's connector for critical refs (if live verification is on)."""
    connectors: dict[str, ProviderProbe | None] = {}
    for source_id, source in sources.items():
        try:
            connectors[source_id] = get_connector(source, services)
        except Exception:  # noqa: BLE001 - misconfigured source: no probe -> never fresh
            connectors[source_id] = None
    live = services.settings.FRESHNESS_LIVE_VERIFY_CRITICAL

    def probe_for(ref: EvidenceRef) -> ProviderProbe | None:
        if live and ref.evidence_class == EvidenceClass.critical:
            return connectors.get(ref.source_id)
        return None

    return probe_for


async def governed_evidence(
    services: Services,
    principal: Principal,
    question: str,
    *,
    top_k: int,
    source_ids: list[str] | None,
    require_fresh: bool,
    request_key: str,
) -> GovernedEvidence:
    s = services.settings
    timing: dict[str, int] = {}

    # 1. retrieval (over-fetch; NOT access-filtered yet)
    t = time.perf_counter()
    hits = await _search(
        services, question, limit=top_k * s.ASK_OVERFETCH_FACTOR, source_ids=source_ids
    )
    retrieved = await _pages_in_rank_order(services, hits)
    timing["retrieval_ms"] = _ms(t)

    # 2-3. access filter: denied pages are dropped here, before any LLM/probe/sanitizer
    t = time.perf_counter()
    evaluated_at = services.clock.now()
    filter_result, allowed = await filter_pages(services, principal, retrieved, now=evaluated_at)
    allowed_ids = {p.id for p in allowed}
    hits = [h for h in hits if h.page_id in allowed_ids]
    timing["access_ms"] = _ms(t)

    # 4. freshness receipt over allowed pages only
    t = time.perf_counter()
    refs = [
        EvidenceRef(
            source_id=p.source_id,
            external_object_id=p.external_object_id,
            connector_kind=ConnectorKind(str(p.source_kind)),
            evidence_class=EvidenceClass(p.evidence_class),
            page_id=p.id,
            page_slug=p.slug,
        )
        for p in allowed
        if p.external_object_id
    ]
    sources = {}
    for source_id in {p.source_id for p in allowed}:
        source = await services.repo.get_source(source_id)
        if source is not None:
            sources[source_id] = source
    receipt = await services.freshness.freshness_receipt(
        ReceiptRequest(request_key=request_key, evidence=refs, allow_empty=True),
        probe_for=_probe_for(services, sources),
    )
    usable_page_ids = {
        item.page_id
        for item in receipt.evidence_items
        if item.page_id
        and item.safe_to_use
        and (not require_fresh or item.freshness_status == FreshnessStatus.fresh)
    }
    timing["freshness_ms"] = _ms(t)

    # 5a. evidence spans (rank order) -> sanitize
    pages_by_id = {p.id: p for p in allowed}
    spans: list[EvidenceSpan] = []
    budget = s.ASK_MAX_CONTEXT_CHARS
    for hit in hits:
        if hit.page_id not in usable_page_ids or len(spans) >= top_k:
            continue
        if budget - len(hit.chunk_text) < 0 and spans:
            break
        budget -= len(hit.chunk_text)
        page = pages_by_id[hit.page_id]
        spans.append(
            EvidenceSpan(
                id=f"E{len(spans) + 1}",
                document_id=page.id,
                chunk_id=hit.chunk_id,
                source_id=page.source_id,
                source_kind=str(page.source_kind),
                slug=page.slug,
                title=page.title,
                text=hit.chunk_text,
                provider_version=page.provider_version,
                content_hash=page.content_hash,
                url=f"{s.PUBLIC_BASE_URL.rstrip('/')}/documents/{page.id}",
                metadata={"chunk_index": hit.chunk_index, "rank": hit.rank},
            )
        )
    sanitized = services.sanitizer.sanitize(spans)
    return GovernedEvidence(
        hits=hits,
        retrieved=retrieved,
        filter_result=filter_result,
        allowed=allowed,
        receipt=receipt,
        usable_page_ids=usable_page_ids,
        spans=spans,
        sanitized=sanitized,
        timing=timing,
        evaluated_at=evaluated_at,
    )


def _receipt_summary(receipt: FreshnessReceipt) -> dict[str, Any]:
    return {
        "receipt_id": receipt.receipt_id,
        "overall_status": str(receipt.overall_status),
        "receipt_hash": receipt.receipt_hash,
        "evidence_items": [
            {
                "page_id": item.page_id,
                "page_slug": item.page_slug,
                "source_id": item.source_id,
                "external_object_id": item.external_object_id,
                "evidence_class": str(item.evidence_class),
                "provider_version": item.provider_version,
                "freshness_status": str(item.freshness_status),
                "verification_result": str(item.verification_result)
                if item.verification_result
                else None,
                "safe_to_use": item.safe_to_use,
                "fallback_action": str(item.fallback_action) if item.fallback_action else None,
                "reason": item.reason,
            }
            for item in receipt.evidence_items
        ],
    }


async def ask(
    services: Services,
    principal: Principal,
    question: str,
    *,
    source_ids: list[str] | None = None,
    top_k: int | None = None,
    require_fresh: bool = False,
    request_id: str | None = None,
) -> AnswerEnvelope:
    s = services.settings
    started_at = utcnow()
    t_total = time.perf_counter()
    request_id = request_id if request_id is not None else get_request_id()
    query_id = new_id()
    top_k = top_k or s.ASK_TOP_K

    ev = await governed_evidence(
        services,
        principal,
        question,
        top_k=top_k,
        source_ids=source_ids,
        require_fresh=require_fresh,
        request_key=f"ask:{query_id}",
    )

    # 5b. compose -> verify -> abstain (only allowed, fresh-enough, sanitized evidence)
    t = time.perf_counter()
    answer = await services.composer.compose(question, ev.sanitized, max_claims=top_k)
    ev.timing["compose_ms"] = _ms(t)
    t = time.perf_counter()
    report = await services.verifier.verify(answer, ev.sanitized)
    ev.timing["verify_ms"] = _ms(t)

    access_summary = AccessSummary.from_filter_result(
        ev.filter_result,
        principal_id=principal.id,
        policy_version=services.access_policy.policy_version,
        evaluated_at=ev.evaluated_at,
    )
    decisions = [
        {
            "document_id": d.document_id,
            "decision": str(d.decision),
            "reason": str(d.reason) if d.reason else None,
            "matched_rule": d.matched_rule,
            "permission_version": d.permission_version,
        }
        for d in ev.filter_result.decisions
    ]

    abstain, abstain_reason = services.abstention.should_abstain(
        report, min_coverage=s.GROUNDING_MIN_COVERAGE
    )
    if answer.abstained:
        abstain, abstain_reason = True, answer.abstain_reason or abstain_reason
    partial_notice: str | None = None
    candidate_grounding: dict[str, Any] | None = None
    dropped_claim_count = 0
    if (
        not answer.abstained
        and report.contradicted == 0
        and answer.composer == f"{MODEL_COMPOSER_ID}+{GROUND_ID}"
        and needs_partial_selection(question, answer, report)
    ):
        selected = select_supported_relevant_claims(question, answer, report)
        if selected is not None:
            t = time.perf_counter()
            selected_report = await services.verifier.verify(selected, ev.sanitized)
            ev.timing["verify_ms"] += _ms(t)
            selected_abstains, _ = services.abstention.should_abstain(
                selected_report, min_coverage=s.GROUNDING_MIN_COVERAGE
            )
            if not selected_abstains:
                candidate_grounding = _grounding_summary(report)
                dropped_claim_count = report.claims_total - len(selected.claims)
                answer, report = selected, selected_report
                abstain, abstain_reason = False, None
                partial_notice = _partial_notice(question)
        if partial_notice is None:
            abstain = True
            abstain_reason = abstain_reason or "insufficient_grounding"
    if (
        not abstain
        and partial_notice is None
        and answer.composer == f"{MODEL_COMPOSER_ID}+{GROUND_ID}"
        and report.supported == report.claims_total
        and procedure_requested(question)
    ):
        candidate_grounding = _grounding_summary(report)
        partial_notice = _partial_notice(question)
    spans_by_id = {span.id: span for span in ev.spans}
    citations: list[CitationOut] = []
    claims = [] if abstain else list(answer.claims)
    if not abstain:
        for c in report.per_claim:
            span = spans_by_id.get(c.evidence_id)
            if span is None:
                continue
            citations.append(
                CitationOut(
                    claim_id=c.claim_id,
                    evidence_id=c.evidence_id,
                    document_id=span.document_id,
                    slug=span.slug,
                    title=span.title,
                    source_id=span.source_id,
                    source_kind=span.source_kind,
                    quote=c.quote,
                    support=c.support,
                    score=c.score,
                    provider_version=span.provider_version,
                    url=span.url,
                )
            )
    answer_text = ABSTAIN_ANSWER_TEXT if abstain else answer.answer_text
    cited_ids = list(dict.fromkeys(c.document_id for c in citations))
    total_ms = _ms(t_total)
    timing = Timing(total_ms=total_ms, **ev.timing)
    status = "abstained" if abstain else "partial" if partial_notice else "answered"

    await services.repo.create_query(
        QueryRecord(
            id=query_id,
            actor_id=principal.id,
            request_id=request_id,
            question=question,
            status=status,
            answer_text=answer_text,
            citations=[c.model_dump(mode="json") for c in citations],
            grounding_report=report.model_dump(mode="json"),
            freshness_receipt_id=ev.receipt.receipt_id,
            access_summary=access_summary.model_dump(mode="json"),
            latency_ms=total_ms,
        )
    )
    event = await audit.record(
        services,
        actor_id=principal.id,
        action="ask",
        subject_type="query",
        subject_id=query_id,
        request_id=request_id,
        payload={
            "question": question,
            "query_id": query_id,
            "retrieved_document_ids": [p.id for p in ev.retrieved],
            "access_decisions": decisions,
            "freshness_receipt": _receipt_summary(ev.receipt),
            "evidence_ids": [span.id for span in ev.spans],
            "answer_text": answer_text,
            "abstained": abstain,
            "abstain_reason": abstain_reason,
            **(
                {
                    "partial_notice": partial_notice,
                    "candidate_grounding": candidate_grounding,
                    "dropped_claim_count": dropped_claim_count,
                }
                if partial_notice is not None
                else {}
            ),
            "cited_document_ids": cited_ids,
            "composer": answer.composer,
            "grounding": {
                "verifier": report.verifier,
                "verdict": str(report.verdict),
                "coverage_ratio": report.coverage_ratio,
                "report_hash": report.report_hash,
                "quarantined_evidence_ids": list(report.quarantined_evidence_ids),
            },
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": utcnow().isoformat(),
        },
    )
    await services.repo.set_query_audit_event(query_id, event.id)

    return AnswerEnvelope(
        query_id=query_id,
        audit_id=event.id,
        answer=AnswerOut(
            text=answer_text,
            abstained=abstain,
            abstain_reason=abstain_reason,
            partial_notice=partial_notice,
        ),
        claims=claims,
        citations=citations,
        freshness_receipt=ev.receipt,
        grounding=report,
        access_summary=access_summary,
        timing=timing,
    )


async def search(
    services: Services,
    principal: Principal,
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    source_id: str | None = None,
) -> list[SearchHit]:
    """ACL-filtered hybrid search hits with each page's current freshness status; no LLM."""
    from app.services.documents import freshness_view

    factor = services.settings.ASK_OVERFETCH_FACTOR
    hits = await _search(
        services,
        query,
        limit=(offset + limit) * factor,
        source_ids=[source_id] if source_id else None,
    )
    pages = await _pages_in_rank_order(services, hits)
    _, allowed = await filter_pages(services, principal, pages)
    allowed_by_id = {p.id: p for p in allowed}
    visible = [h for h in hits if h.page_id in allowed_by_id][offset : offset + limit]
    status_cache: dict[str, str | None] = {}
    out: list[SearchHit] = []
    for rank, hit in enumerate(visible, start=offset + 1):
        if hit.page_id not in status_cache:
            view = await freshness_view(services, allowed_by_id[hit.page_id])
            status_cache[hit.page_id] = view["freshness_status"] if view else None
        out.append(
            hit.model_copy(update={"freshness_status": status_cache[hit.page_id], "rank": rank})
        )
    return out


async def assemble_evidence(
    services: Services,
    principal: Principal,
    query: str,
    *,
    limit: int = 8,
    source_id: str | None = None,
    require_fresh: bool = False,
) -> EvidenceBundle:
    """ACL-filtered, freshness-checked, sanitized evidence spans plus the receipt; no answer.
    Quarantined spans are returned flagged (text withheld) so a caller can see they existed."""
    ev = await governed_evidence(
        services,
        principal,
        query,
        top_k=limit,
        source_ids=[source_id] if source_id else None,
        require_fresh=require_fresh,
        request_key=f"evidence:{uuid4()}",
    )
    status_by_page = {
        item.page_id: str(item.freshness_status) for item in ev.receipt.evidence_items
    }
    spans = [
        EvidenceSpanOut(
            id=item.evidence.id,
            document_id=item.evidence.document_id,
            chunk_id=item.evidence.chunk_id,
            source_id=item.evidence.source_id,
            source_kind=item.evidence.source_kind,
            slug=item.evidence.slug,
            title=item.evidence.title,
            text="" if item.quarantined else item.evidence.text,
            provider_version=item.evidence.provider_version,
            url=item.evidence.url,
            quarantined=item.quarantined,
            was_modified=item.was_modified,
            injection_flags=len(item.flags),
            freshness_status=status_by_page.get(item.evidence.document_id),
        )
        for item in ev.sanitized
    ]
    return EvidenceBundle(
        query=query,
        spans=spans,
        freshness_receipt=ev.receipt,
        access_summary=AccessSummary.from_filter_result(
            ev.filter_result,
            principal_id=principal.id,
            policy_version=services.access_policy.policy_version,
            evaluated_at=ev.evaluated_at,
        ),
        meta={"timing": ev.timing},
    )
