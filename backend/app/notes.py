"""
Notes kept about something — a model, a printer. This is the one place that decides how notes are tidied and how a
save avoids overwriting what someone else has saved, so every kind of notes behaves identically and a fix to one
can't be missed by another.

Each kind has its own small table (see SourceModelNote, PrinterNote): one row per owner, with the text, a
`revision` that only ever goes up, and when it was saved. The owner object exposes `.note_row` and `.notes_revision`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

MAX_NOTES_LENGTH = 20000


def clean(notes: str) -> str:
    """
    Windows line endings become plain ones; blank lines around the text and trailing spaces are dropped. A NUL
    character can't be stored in PostgreSQL text (it would be a server error), so it's removed.
    """
    return notes.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\n").rstrip()


def save(db, *, owner, note_cls, owner_key: str, base_revision: int, notes: str, conflict, reload):
    """
    Save the notes for `owner`. `base_revision` is the revision the person's text was based on (0 = there were
    none). If the stored revision has moved on, someone else saved in between and this raises `conflict(owner)`
    rather than quietly overwriting their work. Clearing the notes saves an empty text (and counts as a revision),
    so a revision number is never reused.

    note_cls / owner_key: the notes table and the name of its key column (e.g. "printer_id").
    conflict: the exception class to raise, built from the owner as it now stands.
    reload: returns the owner freshly read from the database.
    """
    if len(notes) > MAX_NOTES_LENGTH:
        raise ValueError(f"Notes can be at most {MAX_NOTES_LENGTH:,} characters.")

    if base_revision != owner.notes_revision:
        raise conflict(owner)

    text = clean(notes)
    if text == "" and owner.note_row is None:
        return owner  # nothing to clear, and nothing worth a revision

    # The check above is only a quick refusal: two people saving at the very same moment could both pass it. What
    # actually guarantees nobody is overwritten is that the write itself is conditional ("...WHERE revision = the
    # one this text was based on"), so the database lets exactly one of them through and the rest get a conflict.
    owner_id = owner.id
    key = getattr(note_cls, owner_key)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        if owner.note_row is None:
            db.add(note_cls(**{owner_key: owner_id}, body=text, revision=1, updated_at=now))
            db.commit()  # a concurrent first save collides on the primary key
        else:
            done = db.execute(
                update(note_cls)
                .where(key == owner_id, note_cls.revision == base_revision)
                .values(body=text, revision=note_cls.revision + 1, updated_at=now)
            )
            if done.rowcount != 1:
                raise conflict(owner)
            db.commit()
    except (IntegrityError, conflict):
        db.rollback()
        db.expire_all()
        raise conflict(reload()) from None
    db.expire_all()
    return reload()
