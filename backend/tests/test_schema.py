"""Starting up makes missing tables, and adds indexes that existing tables don't have yet."""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401  (registers every table)
from app.database import Base, create_schema

NEW_INDEXES = {
    "print_jobs": "ix_print_jobs_printer_start",
    "printer_energy_readings": "ix_energy_readings_printer_taken",
    "bundles": "ix_bundles_printer_id",
    "bundle_source_models": "ix_bundle_source_models_source_model_id",
}


def _indexes(engine, table):
    return {i["name"] for i in inspect(engine).get_indexes(table)}


def test_an_existing_database_gets_the_indexes_it_is_missing(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'farm.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:  # as a database made before these indexes existed
        for name in NEW_INDEXES.values():
            conn.execute(text(f"DROP INDEX {name}"))
    assert all(name not in _indexes(engine, table) for table, name in NEW_INDEXES.items())
    create_schema(engine)
    assert all(name in _indexes(engine, table) for table, name in NEW_INDEXES.items())
    create_schema(engine)  # and again: nothing to do, no error
