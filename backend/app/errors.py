"""Typed application errors that the API turns into structured responses.

Each error has two messages:

* `str(exc)` keeps the detailed operator text (which may include local paths).
  CLI scripts and logs use it.
* `public_message` is safe to send to API clients: it names versions and
  commands, never filesystem paths.

The subclasses deliberately also inherit the built-in type they replaced
(`RuntimeError`, `ValueError`). Existing `except` clauses in scripts and tests
rely on that; do not remove the second base class.
"""


class GistError(Exception):
    code = "internal_error"
    status = 500

    def __init__(self, message: str, *, public_message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.public_message = public_message
        if code is not None:
            self.code = code


class DatasetStateError(GistError, RuntimeError):
    """The selected database cannot be served: wrong version, legacy, or stale index."""
    status = 503


class SourceFilesMissing(DatasetStateError, FileNotFoundError):
    """The Pulse source set on disk is incomplete. Also a FileNotFoundError for seed.py callers."""
    code = "source_files_missing"


class ConfigurationError(GistError, ValueError):
    """Server configuration (environment) is invalid."""
    code = "invalid_configuration"
    status = 503
