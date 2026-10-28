from __future__ import annotations

from app.models import AppSetting
from app.services import app_settings


def test_a_setting_is_added_changed_and_removed(db_session):
    assert app_settings.get(db_session, "colour") is None

    app_settings.put(db_session, "colour", "green")
    db_session.commit()
    assert app_settings.get(db_session, "colour") == "green"

    app_settings.put(db_session, "colour", "blue")
    db_session.commit()
    assert app_settings.get(db_session, "colour") == "blue"
    assert db_session.query(AppSetting).count() == 1  # changed in place, not added again

    app_settings.put(db_session, "colour", None)
    db_session.commit()
    assert app_settings.get(db_session, "colour") is None
    assert db_session.get(AppSetting, "colour") is None


def test_removing_a_setting_that_was_never_set_is_fine(db_session):
    app_settings.put(db_session, "never", None)
    db_session.commit()
    assert app_settings.get(db_session, "never") is None
