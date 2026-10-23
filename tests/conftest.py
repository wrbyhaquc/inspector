"""Tests run against a throwaway home: never this computer's own settings, packs or runtime folder.

    python -m pytest            (from the program folder; requirements-runtime.txt and pytest are enough)"""
import os
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="inspector-test-")
os.environ["INSPECTOR_HOME"] = HOME                  # before anything imports project: it reads the home once
os.environ["INSPECTOR_EDITION"] = "runtime"          # no PyTorch needed
for k in ("INSPECTOR_CONFIG", "INSPECTOR_DATA", "INSPECTOR_PROJECT", "INSPECTOR_RUNTIME", "INSPECTOR_PACK", "INSPECTOR_WORK"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
