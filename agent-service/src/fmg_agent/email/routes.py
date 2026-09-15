from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth import Principal, require_scope
from .jobs import JobStore
from .urls import public_url

router = APIRouter(prefix="/v1/email")


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=300)
    platform: str | None = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return public_url(value)


def result(request, data):
    return {"data": data, "meta": {"request_id": request.state.request_id}}


@router.post("/enrich", status_code=202)
def enrich(
    request: Request,
    body: EnrichRequest,
    idempotency_key: str = Header(min_length=1, max_length=200),
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(
        request, store.create(principal.id, idempotency_key, body.model_dump())
    )


@router.get("/jobs/{job_id}")
def job(
    request: Request,
    job_id: str,
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(request, store.load(job_id, principal.id))


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(
    request: Request,
    job_id: str,
    principal: Principal = Depends(require_scope("email:enrich")),
):
    store = JobStore(request.app.state.sessions)
    return result(request, store.retry(job_id, principal.id))
