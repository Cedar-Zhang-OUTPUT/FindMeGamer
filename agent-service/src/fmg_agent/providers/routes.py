from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ..auth import require_scope, Principal
from ..usage import Ledger
from ..errors import ApiError
from .transport import call_provider
from .steam_store import call_store

router = APIRouter(
    prefix="/v1/providers", dependencies=[Depends(require_scope("read"))]
)


class CallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    params: dict[str, Any] = {}


@router.get("/{provider}/operations")
def operations(provider: str, request: Request):
    doc = request.app.state.catalog.document(provider)
    return {
        "data": [
            {
                key: operation.get(key)
                for key in ("id", "summary", "availability", "auth")
            }
            for operation in doc["operations"].values()
        ],
        "meta": {
            "request_id": request.state.request_id,
            "source_url": doc["source_url"],
            "verified_date": doc["verified_date"],
        },
    }


@router.get("/{provider}/operations/{operation}")
def describe(provider: str, operation: str, request: Request):
    return {
        "data": request.app.state.catalog.describe(provider, operation),
        "meta": {"request_id": request.state.request_id},
    }


@router.post("/{provider}/call")
async def call(
    provider: str,
    body: CallRequest,
    request: Request,
    principal: Principal = Depends(require_scope("read")),
):
    operation, path, params = request.app.state.catalog.prepare(
        provider, body.operation, body.params
    )
    ledger = Ledger(request.app.state.sessions)
    rid = request.state.request_id
    ledger.start(rid, principal.id, request.state.run_id, provider, body.operation)
    try:
        result = await execute(provider, body, request, operation, path, params)
    except ApiError as error:
        ledger.finish(rid, error.code)
        raise
    except Exception:
        ledger.finish(rid, "execution_unknown")
        raise
    data = result["data"]
    items = (
        data.get("items", data.get("data", data.get("candidates")))
        if isinstance(data, dict)
        else None
    )
    ledger.finish(
        rid,
        "succeeded",
        resource_counts=(
            {"returned_items": len(items)} if isinstance(items, list) else None
        ),
    )
    return result


async def execute(provider, body, request, operation, path, params):
    if provider == "steam" and body.operation in {
        "store.search",
        "store.recommendations",
    }:
        return await call_store(
            operation,
            params,
            request.state.request_id,
            request.app.state.provider_transport,
        )
    return await call_provider(
        request.app.state.settings,
        operation,
        path,
        params,
        provider,
        request.state.request_id,
        request.app.state.provider_transport,
    )
