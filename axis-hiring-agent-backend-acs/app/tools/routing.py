"""CV routing — moves applications into the shortlisted/rejected folders."""

from __future__ import annotations

from ..store import STORE


def move_cv(application_id: str, folder: str) -> str:
    """Move an application to the given folder.

    Folder convention:
      * ``/cvs/shortlisted/{jd_id}/``
      * ``/cvs/rejected/{jd_id}/``
      * ``/cvs/incoming/``
    """
    if not folder.startswith("/cvs/"):
        raise ValueError(f"Folder must start with /cvs/ — got {folder!r}")
    if STORE.get_application(application_id) is None:
        raise LookupError(f"No application found for id={application_id!r}")
    STORE.move_to_folder(application_id, folder)
    return folder
