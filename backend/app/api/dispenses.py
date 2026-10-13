from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.deps import Actor, ClockDep, Cursor, DbSession, Limit
from app.errors import PROBLEM_JSON
from app.schemas import DispenseIn
from app.services import catalog, dispensing

router = APIRouter(tags=["dispenses"])


@router.post(
    "/dispenses",
    status_code=201,
    summary="Record a dispense (idempotent on idempotency_key)",
    responses={
        201: {"description": "Accepted. Replays carry `Idempotent-Replayed: true`."},
        422: {"description": "Rejected (DISPENSE_REJECTED), invalid (VALIDATION_FAILED) or key reused "
              "with a different payload (IDEMPOTENCY_KEY_REUSED)."},
    },
)
def create(body: DispenseIn, db: DbSession, clock: ClockDep, actor: Actor) -> JSONResponse:
    result = dispensing.submit_dispense(db, body, clock=clock, actor=actor)
    return JSONResponse(
        result.body,
        status_code=result.status,
        media_type="application/json" if result.status < 400 else PROBLEM_JSON,
        headers={"Idempotent-Replayed": "true" if result.replayed else "false"},
    )


@router.get("/dispenses", summary="Dispenses, newest first (by dispensed_at)")
def list_(
    db: DbSession,
    limit: Limit,
    cursor: Cursor = None,
    patient_ref: Annotated[str | None, Query(max_length=64)] = None,
    medicine_code: Annotated[str | None, Query(max_length=32)] = None,
) -> dict[str, Any]:
    return catalog.list_dispenses(db, patient_ref, medicine_code, limit, cursor)


@router.get("/dispense-attempts", summary="The attempt log, newest first")
def attempts(
    db: DbSession,
    limit: Limit,
    cursor: Cursor = None,
    patient_ref: Annotated[str | None, Query(max_length=64)] = None,
    outcome: Literal["accepted", "rejected"] | None = None,
) -> dict[str, Any]:
    return catalog.list_attempts(db, patient_ref, outcome, limit, cursor)
