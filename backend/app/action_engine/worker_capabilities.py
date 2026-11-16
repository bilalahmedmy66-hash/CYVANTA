"""Strict capability definitions for CYVANTA security workers."""

WORKER_TYPE_SIMULATION = "simulation"
CAPABILITY_SIMULATION = "simulation"

ALLOWED_WORKER_TYPES = frozenset({
    WORKER_TYPE_SIMULATION,
})

ALLOWED_WORKER_CAPABILITIES = frozenset({
    CAPABILITY_SIMULATION,
})


def normalize_capabilities(capabilities):
    """Validate and normalize a worker capability collection."""
    if isinstance(capabilities, (str, bytes)):
        raise ValueError("Capabilities must be a collection, not a string.")

    try:
        normalized = frozenset(capabilities)
    except TypeError as exc:
        raise ValueError("Capabilities must be an iterable collection.") from exc


    if any(not isinstance(item, str) or not item.strip() for item in normalized):
        raise ValueError("Every capability must be a non-empty string.")

    unsupported = normalized - ALLOWED_WORKER_CAPABILITIES
    if unsupported:
        raise ValueError("One or more worker capabilities are not permitted.")

    return normalized

