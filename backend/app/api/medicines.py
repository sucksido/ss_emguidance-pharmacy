from typing import Annotated, Any

from fastapi import APIRouter, Path, Query

from app.api.deps import NO_NUL, Actor, ClockDep, Cursor, DbSession, Limit
from app.schemas import MedicineDetailOut, NewRuleIn, RuleHistoryOut, SupersedeOut
from app.services import catalog, formulary

router = APIRouter(prefix="/medicines", tags=["medicines"])

Code = Annotated[str, Path(max_length=32, pattern=NO_NUL)]


@router.get("", summary="Search medicines by partial name or code")
def search(
    db: DbSession,
    limit: Limit,
    cursor: Cursor = None,
    q: Annotated[str | None, Query(max_length=100, pattern=NO_NUL)] = None,
) -> dict[str, Any]:
    return catalog.search_medicines(db, q, limit, cursor)


@router.get("/{code}", response_model=MedicineDetailOut, summary="Medicine with the rule in force today")
def detail(code: Code, db: DbSession, clock: ClockDep) -> MedicineDetailOut:
    return catalog.medicine_detail(db, code, clock)


@router.get("/{code}/rules", response_model=RuleHistoryOut, summary="Full rule history, oldest first")
def rules(code: Code, db: DbSession, clock: ClockDep) -> RuleHistoryOut:
    return catalog.rule_history(db, code, clock)


@router.post(
    "/{code}/rules",
    response_model=SupersedeOut,
    status_code=201,
    summary="Introduce a rule from a date, superseding the rule in force then",
)
def add_rule(code: Code, body: NewRuleIn, db: DbSession, clock: ClockDep, actor: Actor) -> SupersedeOut:
    return formulary.supersede(db, code, body, clock=clock, actor=actor)
