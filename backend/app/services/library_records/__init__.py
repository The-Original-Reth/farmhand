"""
The Models library on the NAS with what it is: a record beside each model's files (in the STL folder) and each 3MF's
(in the 3MF folder), like a project's (project_records): the model's name, type, notes and every version's file; the
3MF's printer, the models it was sliced from, notes, starred version, and every version's 3MF, G-code, preview,
monument and slicer settings (so a version whose files were pruned comes back too).

So the library isn't only in this Farmhand's database: another Farmhand sharing the folders (or a new one after this
computer is gone) brings every model and 3MF in from them, its files used where they are. Each Farmhand writes its own
record (farmhand-model-<its id>.json, farmhand-3mf-<its id>.json), so two never write over each other's: for every
model and 3MF it has, in the folder its files are in (its own, or one another Farmhand filed them in). Where two
Farmhands' records describe the same files, the one saved last is the one brought in.
"""
from ..app_settings import instance_id
from .importing import fill_sub_printers, import_bundles, import_library, import_models
from .moved import drop_doubles, relink_moved_models
from .reading import FORMAT, MAX_RECORD_BYTES, MODEL_PREFIX, THREEMF_PREFIX, files_kept_by_others, log
from .writing import background, request_write, write_all, write_bundle, write_model

__all__ = [
    "FORMAT", "MAX_RECORD_BYTES", "MODEL_PREFIX", "THREEMF_PREFIX", "background", "drop_doubles", "files_kept_by_others",
    "fill_sub_printers", "import_bundles", "import_library", "import_models", "instance_id", "log", "relink_moved_models",
    "request_write", "write_all", "write_bundle", "write_model",
]
