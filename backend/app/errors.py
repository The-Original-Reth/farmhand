"""
Turning what the services raise into API answers, in one place:
  NotFound (the thing asked for doesn't exist) -> 404
  ValueError (it can't be done as asked)        -> 422, or the route's own code (e.g. 409 for a clash)
both with the error's own message. Anything else is a real fault and stays a 500.
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException


class NotFound(LookupError):
    """The model, printer, 3MF, version... asked for doesn't exist."""


@contextmanager
def answer_errors(invalid: int = 422):
    try:
        yield
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=invalid, detail=str(e)) from None
