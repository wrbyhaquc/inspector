"""Web UI backend of Inspector: the pages and their API (see app.py)."""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import project

DATA_ROOT = project.data_root()        # the design: project.json + meta/
WORK_ROOT = project.work_root()        # sessions, labels, testset, models, shadow, caches (the same folder in the
                                       # single-folder layout)
# files the running script rewrites every second (live previews, status, control switches): on a fast SSD,
# not on the data disk (an HDD). Logs, audit frames and flagged frames stay under DATA_ROOT/shadow.
RUNTIME_DIR = project.runtime_dir()
