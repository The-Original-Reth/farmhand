"""
Everything Farmhand does on its own once it's started, without anyone opening a page: keeping network shares mounted,
syncing printers, saving each month's Farm cost record, copying settings to the settings folder, writing the records
beside the files on the NAS and bringing in what another Farmhand sharing the folders has, and a few one-off tidy-ups
of data from older versions. Each runs on a thread of its own, so a slow NAS or printer never delays the API.
"""
from __future__ import annotations

import logging
import threading

from . import storage
from .database import SessionLocal
from .farm_cost_recorder import recorder as farm_cost_recorder
from .mount_supervisor import supervisor
from .periodic import PeriodicWorker
from .printer_poller import poller
from .services import bundle_service, config_service, library_records, previews, project_records, project_scan, sub_printer_service

log = logging.getLogger("farmhand.startup")


class SharedFoldersWorker(PeriodicWorker):
    """
    A minute after starting (when the shares are mounted), every model's, 3MF's and project's record written beside its
    files once; then, every few minutes, what another Farmhand sharing the folders has (or project folders dropped in)
    brought in.
    """

    name, failure, log = "projects-folder", "Scanning the project files folder failed", log

    def __init__(self):
        super().__init__(interval=300, first_wait=60)
        self._written = False

    def run_once(self) -> None:
        if not self._written:
            self._written = True
            try:
                with SessionLocal() as db:
                    library_records.write_all(db)
                    project_records.write_all(db)
            except Exception:  # noqa: BLE001 - the scan below still runs
                log.exception("Writing the records failed")
        try:
            with SessionLocal() as db:
                library = library_records.import_library(db)  # models and 3MFs first: projects name them
                result = project_scan.import_projects_folder(db, auto=True)
        except storage.StorageUnavailableError:
            return  # the folder is away: next time
        for name in library["models"] + library["threemfs"]:
            log.info("Brought in %s from the shared folders", name)
        for p in result["imported"]:
            log.info("Brought in the project %s from the project files folder", p["name"])


class PreviewsWorker(PeriodicWorker):
    """
    Previews are kept only next to their files. Copies the app kept itself (from before) are moved out to their files:
    a minute after starting (once the saved network shares are mounted), then every hour for shares that come back
    later.
    """

    name, failure, log = "previews-beside", "Moving previews out to their files failed", log

    def __init__(self):
        super().__init__(interval=3600, first_wait=60)

    def run_once(self) -> None:
        with SessionLocal() as db:
            moved = previews.move_app_copies_out(db)
        if moved:
            log.info("Moved %d preview(s) out of the app to their files", moved)


shared_folders = SharedFoldersWorker()
previews_worker = PreviewsWorker()


def start_all() -> None:
    # Re-mount saved network shares (and keep them mounted)
    supervisor.start()
    # Sync every printer's history and power meter now and then, so energy figures build up on their own
    poller.start()
    # Once a month is over, its Farm cost table is saved as a record in the "farm-cost" folder
    farm_cost_recorder.start()
    # Changes to printers and models get copied to the settings folder in the background, and once now
    config_service.enable_background_mirror()
    config_service.request_mirror()
    previews_worker.start()
    # Records written beside the files after every change, and what another Farmhand shares brought in
    project_records.background.enable()
    library_records.background.enable()
    shared_folders.start()
    # 3MF versions from before printer profiles: linked to the printer preset each was sliced with, once
    threading.Thread(target=sub_printer_service.run_link_missing, args=(SessionLocal,), name="sub-printers", daemon=True).start()
    # 3MFs from before auto-starring: each one's newest version starred, once
    threading.Thread(target=bundle_service.run_star_existing, args=(SessionLocal,), name="stars", daemon=True).start()


def stop_all() -> None:
    for worker in (supervisor, poller, farm_cost_recorder, previews_worker, shared_folders):
        worker.stop()
