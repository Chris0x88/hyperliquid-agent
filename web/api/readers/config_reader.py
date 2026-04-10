"""JSON/YAML config file reader with atomic writes and backups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from web.api.readers.base import ConfigReader as BaseConfigReader

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


class FileConfigReader(BaseConfigReader):
    """Reads and writes config files from data/config/."""

    def __init__(self, config_dir: Path):
        self._dir = config_dir

    def list_configs(self) -> list[dict]:
        if not self._dir.exists():
            return []
        configs = []
        for f in sorted(self._dir.iterdir()):
            if f.suffix in (".json", ".yaml", ".yml"):
                configs.append({
                    "filename": f.name,
                    "type": "yaml" if f.suffix in (".yaml", ".yml") else "json",
                    "size_bytes": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        return configs

    def read_config(self, filename: str) -> dict[str, Any]:
        path = self._dir / filename
        if not path.exists():
            return {"error": f"Config file not found: {filename}"}

        text = path.read_text()
        if path.suffix in (".yaml", ".yml"):
            if yaml is None:
                return {"error": "PyYAML not installed"}
            return yaml.safe_load(text) or {}
        return json.loads(text)

    def write_config(self, filename: str, data: dict[str, Any]) -> None:
        path = self._dir / filename
        # Backup existing file
        if path.exists():
            bak = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, bak)

        tmp = path.with_suffix(".tmp")
        if path.suffix in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("PyYAML not installed")
            tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        else:
            tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
