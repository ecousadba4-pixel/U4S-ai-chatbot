from pathlib import Path
import sys

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.tests._helpers import load_app_module


@pytest.fixture()
def app_module(monkeypatch):
    return load_app_module(monkeypatch)
