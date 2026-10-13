"""Named no-op hooks at the points where a race would do damage.

Production behaviour is unaffected (``reached`` does nothing). The concurrency
tests monkeypatch ``reached`` to *pause* a transaction exactly between "read
the 30-day window" and "insert the dispense", which is how they prove that two
requests genuinely overlapped instead of happening to run one after the other.
"""


def reached(name: str) -> None:  # pragma: no cover - intentionally empty
    return None
