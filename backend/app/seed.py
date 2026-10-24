"""
Populate the database with real data: the two printers, three source
models, and three 3MF bundles this whole project was built and tested
against. Run once against a fresh database so there's something real to
look at immediately.

    docker compose exec api python -m app.seed

Safe to re-run — skips anything that already exists by name rather than
creating duplicates.

Note on gcode: we never had real gcode files for these bundles (only the
.3mf and .stl source files), so a small placeholder gcode is uploaded
alongside each real .3mf. Per spec, 3MF and gcode are always uploaded
together — this seed just doesn't have a real one to pair with.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from .database import Base, SessionLocal, engine
from .models import SourceFileType
from .services import bundle_service, printer_service, source_model_service

SEED_DIR = Path(__file__).parent.parent / "seed_data"

PLACEHOLDER_GCODE = b"; placeholder gcode -- no real gcode file was available when this was seeded\nG28\n"


def _fake_gcode() -> io.BytesIO:
    return io.BytesIO(PLACEHOLDER_GCODE)


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        vt1190 = printer_service.find_by_name(db, "VT 1190")
        if vt1190 is None:
            vt1190 = printer_service.create_printer(
                db, name="VT 1190", kind="Voron Trident (Klipper / Moonraker)", wired_ip="10.0.6.21", wireless_ip=None
            )
            print("created printer: VT 1190")

        v2bog = printer_service.find_by_name(db, "V2 BOG")
        if v2bog is None:
            v2bog = printer_service.create_printer(
                db, name="V2 BOG", kind="Voron 2.4 (Klipper / Moonraker)", wired_ip="10.0.6.34", wireless_ip="10.0.6.134"
            )
            print("created printer: V2 BOG")

        existing = {m.name: m for m in source_model_service.list_source_models(db)}

        def ensure_model(name: str, stl_filename: str) -> int:
            if name in existing:
                return existing[name].id
            with open(SEED_DIR / stl_filename, "rb") as f:
                model = source_model_service.create_source_model(
                    db, name=name, file_type=SourceFileType.stl, file_obj=f
                )
            print(f"created source model: {name} (thumbnail: {'yes' if model.latest_version.thumbnail_path else 'no'})")
            return model.id

        shark_id = ensure_model("MMMini_GreatWhiteShark_v01.stl", "MMMini_GreatWhiteShark_v01.stl")
        frog_v_id = ensure_model("MMMini_Frog_verticalEyes_v01.stl", "MMMini_Frog_verticalEyes_v01.stl")
        frog_h_id = ensure_model(
            "MMMini_Frog_horizontalEyes_Keychain_v01.stl", "MMMini_Frog_horizontalEyes_Keychain_v01.stl"
        )

        existing_shark_vt = bundle_service.list_bundles_for_printer(db, vt1190.id)
        has_shark_vt = any(shark_id in [m.id for m in b.source_models] for b in existing_shark_vt)
        if not has_shark_vt:
            with open(SEED_DIR / "VT_1190_-_prusa_slicer_-_MMMini_GreatWhiteShark_v01.3mf", "rb") as f:
                bundle_service.create_bundle(
                    db,
                    source_model_ids=[shark_id],
                    threemf_file_obj=f,
                    threemf_filename="VT_1190_-_prusa_slicer_-_MMMini_GreatWhiteShark_v01.3mf",
                    gcode_file_obj=_fake_gcode(),
                    gcode_filename="shark_vt1190.gcode",
                    printer_id=vt1190.id,
                )
            print("created bundle: Shark on VT 1190")

        existing_shark_bog = bundle_service.list_bundles_for_printer(db, v2bog.id)
        has_shark_bog = any(shark_id in [m.id for m in b.source_models] for b in existing_shark_bog)
        if not has_shark_bog:
            with open(SEED_DIR / "V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v01.3mf", "rb") as f:
                bundle_service.create_bundle(
                    db,
                    source_model_ids=[shark_id],
                    threemf_file_obj=f,
                    threemf_filename="V2_BOG_-_Prusa_Slicer_-_MMMini_GreatWhiteShark_v01.3mf",
                    gcode_file_obj=_fake_gcode(),
                    gcode_filename="shark_v2bog.gcode",
                    printer_id=v2bog.id,
                )
            print("created bundle: Shark on V2 BOG")

        vt_bundles_now = bundle_service.list_bundles_for_printer(db, vt1190.id)
        has_frog = any(
            {frog_v_id, frog_h_id} & {m.id for m in b.source_models} for b in vt_bundles_now
        )
        if not has_frog:
            with open(SEED_DIR / "VT_1190_-_prusa_slicer_-_MMMini_Frog.3mf", "rb") as f:
                bundle_service.create_bundle(
                    db,
                    source_model_ids=[frog_v_id, frog_h_id],  # mixed plate — the many-to-many case
                    threemf_file_obj=f,
                    threemf_filename="VT_1190_-_prusa_slicer_-_MMMini_Frog.3mf",
                    gcode_file_obj=_fake_gcode(),
                    gcode_filename="frog_vt1190.gcode",
                    printer_id=vt1190.id,
                )
            print("created bundle: Frog (mixed plate) on VT 1190")

        print("seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    if not SEED_DIR.exists():
        print(f"seed_data/ not found at {SEED_DIR} — nothing to seed", file=sys.stderr)
        sys.exit(1)
    seed()
