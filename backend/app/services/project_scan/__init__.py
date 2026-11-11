"""
Scan projects, in three parts:
  copy_in.py      a folder on the NAS whose subfolders are projects: each one's files copied into a new project
  check.py        every project's files against the disk, and files in the project files folder no project has
  folder_sync.py  the project files folder brought in as it is (another Farmhand's projects, or folders dropped in)
common.py has what they share (which files count, each one's kind, Farmhand's own folders).
"""
from .check import check_files
from .common import ProjectExists
from .copy_in import import_folder, scan_folder
from .folder_sync import import_projects_folder, scan_projects_folder

__all__ = ["ProjectExists", "check_files", "import_folder", "import_projects_folder", "scan_folder", "scan_projects_folder"]
