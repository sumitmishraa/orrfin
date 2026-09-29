"""Business-rule refusals, independent of HTTP (BUILD_PLAN §9).

Services raise these; app.main turns them into responses with the same status code and
a plain-English `detail`, so the UI can show the reason exactly as the rule states it.
"""


class DomainError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    status_code = 404


class Forbidden(DomainError):
    """The user is not allowed to do this (role, segregation of duties, approval limit)."""
    status_code = 403


class Conflict(DomainError):
    """The record is not in a state where this can happen (e.g. a step out of order)."""
    status_code = 409


class Invalid(DomainError):
    """The input breaks a rule (e.g. a rejection without a reason)."""
    status_code = 422
