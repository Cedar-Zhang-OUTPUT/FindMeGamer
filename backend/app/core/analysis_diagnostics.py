"""Bounded, content-free analysis diagnostics. Never persist provider bodies."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import logging
import re
from time import monotonic
from uuid import UUID, uuid4

import httpx

logger = logging.getLogger(__name__)
_context = ContextVar("analysis_diagnostic_context", default=None)
_call = ContextVar("analysis_diagnostic_call", default=None)
_last_call = ContextVar("analysis_diagnostic_last_call", default=None)


@contextmanager
def diagnostic_context(**values):
    context = dict(_context.get() or {})
    for key in ("job_id", "search_id", "creator_id"):
        if values.get(key) is not None:
            try:
                context[key] = str(UUID(str(values[key])))
            except (ValueError, TypeError, AttributeError):
                pass
    node = values.get("node_key")
    target = values.get("creator_target")
    if isinstance(target, str):
        context["creator_ref"] = sha256(target.encode("utf-8")).hexdigest()
    if isinstance(node, str) and re.fullmatch(
        r"(?:batch|source|visual|contact|brief|reduce):v[0-9]+(?::[a-z0-9-]{1,50})?",
        node,
    ):
        context["node_key"] = node
    token = _context.set(context)
    last = _last_call.set(None)
    try:
        yield
    finally:
        _last_call.reset(last)
        _context.reset(token)


def emit(event, **fields):
    # Call sites supply code-owned fields only. No exception text/repr/traceback.
    logger.info(
        "%s",
        json.dumps(
            {"event": event, **(_context.get() or {}), **fields}, separators=(",", ":")
        ),
    )


def category(error):
    if isinstance(error, httpx.TimeoutException):
        return "network_timeout"
    if isinstance(error, httpx.TransportError):
        return "network"
    code = getattr(error, "code", None)
    if code in ("deepseek_model_evidence_invalid", "deepseek_model_contacts_invalid"):
        return "evidence"
    if code == "deepseek_model_output_invalid":
        return "schema"
    return "internal"


@contextmanager
def model_call(*, provider, model, schema, attempt, max_tokens):
    call_id = str(uuid4())
    allowed_models = {
        "deepseek-flash",
        "deepseek-pro",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp",
        "gemini-3.8-flash",
    }
    fields = dict(
        call_id=call_id,
        provider=provider,
        model=model if model in allowed_models else "configured_model",
        schema=schema,
        attempt=attempt,
        max_tokens=max_tokens,
    )
    span = {"finish_reason": None, "output_bytes": None, "usage": {}}
    token = _call.set(span)
    _last_call.set(call_id)
    started = monotonic()
    emit("model_call_started", **fields)
    try:
        yield span
    except Exception as error:
        span.setdefault("category", category(error))
        emit(
            "model_call_finished",
            **fields,
            **span,
            status="failed",
            duration_ms=round((monotonic() - started) * 1000, 2),
        )
        raise
    else:
        emit(
            "model_call_finished",
            **fields,
            **span,
            status="succeeded",
            duration_ms=round((monotonic() - started) * 1000, 2),
        )
    finally:
        _call.reset(token)
        _last_call.set(call_id)


def failure_category(value):
    span = _call.get()
    if span is not None:
        span["category"] = value


def response_metadata(envelope, *, gemini=False):
    span = _call.get()
    if span is None or not isinstance(envelope, dict):
        return
    entries = envelope.get("candidates" if gemini else "choices")
    first = (
        entries[0]
        if isinstance(entries, list) and entries and isinstance(entries[0], dict)
        else {}
    )
    reason = first.get("finishReason" if gemini else "finish_reason")
    allowed = {
        "stop",
        "length",
        "insufficient_system_resource",
        "content_filter",
        "tool_calls",
        "STOP",
        "MAX_TOKENS",
        "SAFETY",
        "RECITATION",
        "OTHER",
    }
    span["finish_reason"] = (
        reason
        if isinstance(reason, str) and reason in allowed
        else None if reason is None else "other"
    )
    if gemini:
        content = first.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        texts = (
            [
                p["text"]
                for p in parts
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            ]
            if isinstance(parts, list)
            else []
        )
        span["output_bytes"] = sum(len(t.encode("utf-8")) for t in texts)
    else:
        message = first.get("message", {})
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            span["output_bytes"] = len(content.encode("utf-8"))
    usage = envelope.get("usageMetadata" if gemini else "usage", {})
    mapping = (
        {
            "promptTokenCount": "prompt_tokens",
            "candidatesTokenCount": "completion_tokens",
            "totalTokenCount": "total_tokens",
            "thoughtsTokenCount": "reasoning_tokens",
        }
        if gemini
        else {k: k for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
    )
    if isinstance(usage, dict):
        for source, target in mapping.items():
            value = usage.get(source)
            if type(value) is int and 0 <= value <= 10**12:
                span["usage"][target] = value
        details = usage.get("completion_tokens_details")
        value = details.get("reasoning_tokens") if isinstance(details, dict) else None
        if type(value) is int and 0 <= value <= 10**12:
            span["usage"]["reasoning_tokens"] = value


def evidence_failure(schema, attempt, reason="evidence_catalog_mismatch"):
    emit(
        "analysis_evidence_rejected",
        schema=schema,
        stage_attempt=attempt,
        call_id=_last_call.get(),
        category="evidence",
        reason=reason,
    )


def traced_node(node_key, call):
    with diagnostic_context(node_key=node_key):
        started = monotonic()
        emit("analysis_node_started")
        try:
            result = call()
        except Exception as error:
            emit(
                "analysis_node_finished",
                status="failed",
                category=category(error),
                call_id=_last_call.get(),
                duration_ms=round((monotonic() - started) * 1000, 2),
            )
            raise
        emit(
            "analysis_node_finished",
            status="succeeded",
            duration_ms=round((monotonic() - started) * 1000, 2),
        )
        return result
