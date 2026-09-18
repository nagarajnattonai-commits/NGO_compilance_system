"""Shared lifecycle classification. Closure is distinct from successful completion."""
CLOSED_STATES = frozenset({"COMPLETED", "CANCELLED", "NOT_APPLICABLE"})
EXCLUDED_STATES = CLOSED_STATES - {"COMPLETED"}


def is_open(status: str) -> bool:
    return status not in CLOSED_STATES


def counts_toward_completion(status: str) -> bool:
    return status not in EXCLUDED_STATES
