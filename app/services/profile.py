from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings

PROFILE_PATH = Path("data/arnav_profile.yaml")


def load_profile(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or get_settings().project_root
    profile_path = root / PROFILE_PATH
    if not profile_path.exists():
        raise FileNotFoundError(profile_path)
    loaded = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Profile YAML must contain a mapping.")
    return loaded

