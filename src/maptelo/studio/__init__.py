"""Maptelo Studio: the processes, their runs and their proof, on this computer.

    maptelo studio --workspace C:\\Maptelo

A page served on 127.0.0.1 only (see ``app``), over the same folders the command line uses
(see ``workspace``). Runs go on in the background, one at a time (see ``jobs``, ``runs``).
"""

from maptelo.studio.app import create_app
from maptelo.studio.jobs import Job, Jobs
from maptelo.studio.server import serve
from maptelo.studio.workspace import Process, Workspace

__all__ = ["Job", "Jobs", "Process", "Workspace", "create_app", "serve"]
