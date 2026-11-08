from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, models  # noqa: F401 registers all models on Base
from app import storage
from app.database import Base, get_db
from app.main import app
from app import mounts, printer_links
from app.services.moonraker import client as mr_client
from app.services.prusalink import client as pl_client

from .fake_moonraker import FakeMoonraker
from .fake_nas import FakeNas
from .fake_prusalink import FakePrusaLink


@pytest.fixture(autouse=True)
def _no_remembered_addresses(monkeypatch):
    """Where each printer last answered is forgotten between tests: every test's database starts its ids over."""
    monkeypatch.setattr(printer_links, "_answered", {})


# Tests of POSIX behaviour (file permissions, "/" paths, real mounts) only mean something on Linux, where Farmhand
# runs (Docker). Elsewhere they're skipped, saying why.
posix_only = pytest.mark.skipif(os.name == "nt", reason="checks POSIX behaviour (file permissions, / paths); runs on Linux and in Docker")


def symlink(target, link) -> None:
    """os.symlink, or skip the test where symlinks can't be made (Windows without Developer Mode or admin rights)."""
    try:
        os.symlink(target, link)
    except OSError as e:
        if os.name == "nt":
            pytest.skip(f"symlinks can't be made here ({e.strerror}); runs on Linux and in Docker")
        raise


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
def api(tmp_path, monkeypatch):
    """A TestClient on an empty database, with file storage in tmp_path/storage."""
    # FastAPI runs handlers on worker threads, so this needs a database that may be used from any thread
    # (db_session's in-memory SQLite is tied to the thread that created it).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(config.settings, "storage_root", str(tmp_path / "storage"))
    storage.reset()

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)  # no `with`: the app's startup (which wants Postgres) isn't run
    app.dependency_overrides.clear()
    storage.reset()


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


# ------------------------------------------------------------------ printers, NAS shares and a second Farmhand


@pytest.fixture()
def moonraker(monkeypatch):
    """A Klipper printer's Moonraker (tests/fake_moonraker.py), answering every address Farmhand asks."""
    f = FakeMoonraker()
    monkeypatch.setattr(mr_client, "transport", httpx.MockTransport(f.handle))
    return f


@pytest.fixture()
def prusalink(monkeypatch):
    """A Prusa printer's PrusaLink (tests/fake_prusalink.py), answering every address Farmhand asks."""
    f = FakePrusaLink()
    monkeypatch.setattr(pl_client, "transport", httpx.MockTransport(f.handle))
    return f


@pytest.fixture()
def klipper(api, moonraker):
    """The API, and the id of a Klipper printer (VT 1190 at 10.0.6.21) whose Moonraker answers: (api, printer id)."""
    printer = api.post("/printers", json={"name": "VT 1190", "kind": "Voron", "wired_ip": "10.0.6.21"}).json()
    return api, printer["id"]


@pytest.fixture()
def share(tmp_path, monkeypatch):
    """A fake *connected* NAS share (a mount point, tmp_path/data/nas/lab) inside the area the pages may browse."""
    area = tmp_path / "data"
    nas = area / "nas" / "lab"
    nas.mkdir(parents=True)
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    real = str(nas.resolve())
    monkeypatch.setattr(storage, "_is_mount", lambda p: os.path.realpath(p) == real)
    return nas


@pytest.fixture()
def nas(tmp_path, monkeypatch):
    area = tmp_path / "data"
    area.mkdir()
    monkeypatch.setattr(config.settings, "storage_browse_root", str(area))
    fake = FakeNas()
    monkeypatch.setattr(mounts, "mount", fake.mount)
    monkeypatch.setattr(mounts, "unmount", fake.unmount)
    monkeypatch.setattr(mounts, "is_mounted", fake.is_mounted)
    monkeypatch.setattr(storage, "_is_mount", fake.is_mounted)
    monkeypatch.setattr(mounts, "mount_capability", lambda *a, **k: {"ok": True, "smb": True, "nfs": True, "message": None, "smb_message": None, "nfs_message": None})
    mounts._errors.clear()
    yield fake
    storage.reset()
    mounts._errors.clear()


@pytest.fixture()
def other_farmhand():
    """A second Farmhand: its own (empty) database, sharing the same folders."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    yield db
    db.close()
