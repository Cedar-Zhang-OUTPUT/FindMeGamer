from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ..auth import require_scope
from .transport import call_provider

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
async def call(provider: str, body: CallRequest, request: Request):
    operation, path, params = request.app.state.catalog.prepare(
        provider, body.operation, body.params
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
