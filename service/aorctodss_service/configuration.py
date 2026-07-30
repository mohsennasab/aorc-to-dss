"""Runtime configuration and safe local paths."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ServiceConfiguration:
    """Configuration persisted under the user profile."""

    workspace: str
    cache: str
    max_concurrent_downloads: int = 4
    request_timeout_seconds: int = 90
    retry_count: int = 3

    @classmethod
    def default(cls) -> "ServiceConfiguration":
        """Build a platform-neutral default."""

        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AORCtoDSS"
        return cls(workspace=str(base / "workspace"), cache=str(base / "cache"))

    @classmethod
    def load(cls, path: Path | None = None) -> "ServiceConfiguration":
        """Load configuration or create defaults."""

        config_path = path or cls.default_path()
        if not config_path.exists():
            config = cls.default()
            config.save(config_path)
            return config
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls(**data)

    @staticmethod
    def default_path() -> Path:
        """Return the default configuration file."""

        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AORCtoDSS"
        return base / "config.json"

    def save(self, path: Path | None = None) -> None:
        """Save configuration with its parent directory."""

        config_path = path or self.default_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def ensure_directories(self) -> None:
        """Create the configured runtime directories."""

        Path(self.workspace).mkdir(parents=True, exist_ok=True)
        Path(self.cache).mkdir(parents=True, exist_ok=True)
