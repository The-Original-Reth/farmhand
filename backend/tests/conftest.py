from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 registers all models on Base
from app import storage
from app.database import Base


@pytest.fixture()
def db_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, future=True)
    session = TestingSession()

    # Point file storage at a scratch temp dir for the duration of the test
    tmp_storage = tempfile.mkdtemp(prefix="farmhand-test-storage-")
    from app import config

    monkeypatch.setattr(config.settings, "storage_root", tmp_storage)

    storage.reset()
    yield session
    storage.reset()

    session.close()
    shutil.rmtree(tmp_storage, ignore_errors=True)


@pytest.fixture()
def sample_3mf_paths():
    """
    Real 3MF files from the print farm, bundled into tests/fixtures/ so the
    test suite is self-contained. Falls back to /mnt/user-data/uploads for
    convenience when running inside the original chat environment.
    """
    fixtures_dir = Path(__file__).parent / "fixtures"
    fallback_dir = Path("/mnt/user-data/uploads")

    names = {
        "frog_vt1190": "VT_1190_-_prusa_slicer_-_MMMini_Frog.3mf",
        "shark_vt1190": "VT_1190_-_prusa_slicer_-_MMMini_GreatWhiteShark_v01.3mf",
        "shark_v2bog": "V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v01.3mf",
    }

    paths = {}
    for key, filename in names.items():
        candidate = fixtures_dir / filename
        if not candidate.exists():
            candidate = fallback_dir / filename
        paths[key] = candidate

    if not all(p.exists() for p in paths.values()):
        pytest.skip("Real sample .3mf files not found in tests/fixtures/ or /mnt/user-data/uploads")
    return {k: str(v) for k, v in paths.items()}
