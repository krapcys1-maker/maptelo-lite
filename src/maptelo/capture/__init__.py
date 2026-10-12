"""Capturing demonstrations: the browser recorder and importers of other formats."""

from maptelo.capture.devtools import DevToolsImportError, import_devtools_file
from maptelo.capture.redact import redact_secrets
from maptelo.capture.web import Recorder, RecorderOptions, new_recording_id, record_session

__all__ = [
    "DevToolsImportError",
    "Recorder",
    "RecorderOptions",
    "import_devtools_file",
    "new_recording_id",
    "record_session",
    "redact_secrets",
]
