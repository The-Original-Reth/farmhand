"""
Turning what the engine raises into API answers (as Farmhand's app/errors.py): NotFound -> 404, ValueError -> 422 (or
the route's own code), both with the error's own message.
"""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException


class NotFound(LookupError):
    """The picture, slideshow, track... asked for isn't there."""


@contextmanager
def answer_errors(invalid: int = 422):
    try:
        yield
    except NotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=invalid, detail=str(e)) from None
