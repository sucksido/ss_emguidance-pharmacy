from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.timeutil import Clock, SystemClock

_system_clock = SystemClock()


def get_clock(request: Request) -> Clock:
    # Tests install a FixedClock on app.state; production uses the system clock.
    return getattr(request.app.state, "clock", None) or _system_clock


def get_actor(x_actor: Annotated[str | None, Header(max_length=100)] = None) -> str | None:
    """Stub identity (authentication is out of scope). Recorded for audit only."""
    return x_actor


def page_limit(limit: Annotated[int | None, Query(ge=1)] = None) -> int:
    s = get_settings()
    return min(limit or s.default_page_size, s.max_page_size)


DbSession = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[Clock, Depends(get_clock)]
Actor = Annotated[str | None, Depends(get_actor)]
Limit = Annotated[int, Depends(page_limit)]
Cursor = Annotated[str | None, Query(max_length=500)]
