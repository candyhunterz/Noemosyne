"""Stable domain errors returned through every machine interface."""


class DomainError(ValueError):
    """A violation of a named epistemic invariant."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ConflictError(DomainError):
    """A state or revision precondition was not met."""


class NotFoundError(DomainError):
    """A requested epistemic object does not exist at the requested cutoff."""
