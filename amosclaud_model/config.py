from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ModelConfig:
    name: str = "amosclaud-folder-v1"
    order: int = 4
    max_tokens: int = 512
    temperature: float = 0.35
    seed: int = 7

    @classmethod
    def load(cls, root: Path) -> "ModelConfig":
        path = root / "config" / "model.json"
        if not path.exists():
            return cls()
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, root: Path) -> None:
        path = root / "config" / "model.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


def model_root() -> Path:
    return Path(os.getenv("AMOSCLAUD_MODEL_HOME", "data/amosclaud-model")).expanduser().resolve()
