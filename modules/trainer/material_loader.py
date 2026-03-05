"""
MaterialLoader — reads formation material from material/<formation_dir>/.

Trainer-internal utility. Not a service. Instantiated by TrainerManager.
material_root is auto-detected as project_root/material/ where project_root
is the parent of the directory containing this file's module root (modules/).
"""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from core.logging import log


def _get_material_root() -> Path:
    """Auto-detect material/ directory as sibling of modules/."""
    # modules/trainer/material_loader.py → modules/ → project_root/
    modules_dir = Path(__file__).parent.parent
    return modules_dir.parent / "material"


class MaterialLoader:
    def __init__(self, material_root: Optional[Path] = None):
        self.material_root = material_root or _get_material_root()

    def list_formations(self) -> List[str]:
        """Return sorted list of subdirectory names in material_root."""
        if not self.material_root.exists():
            log("warning", f"MaterialLoader: material root not found: {self.material_root}")
            return []
        return sorted([
            d.name for d in self.material_root.iterdir()
            if d.is_dir() and (d / "program.md").exists()
        ])

    def formation_exists(self, formation_dir: str) -> bool:
        """Check if material/<formation_dir>/ exists and has program.md."""
        path = self.material_root / formation_dir
        return path.is_dir() and (path / "program.md").exists()

    def get_program(self, formation_dir: str) -> str:
        """
        Read and return material/<formation_dir>/program.md as string.
        Raises FileNotFoundError with a clear message if not found.
        """
        path = self.material_root / formation_dir / "program.md"
        if not path.exists():
            raise FileNotFoundError(
                f"MaterialLoader: program.md not found at {path}. "
                f"Check that formation_dir '{formation_dir}' is correct."
            )
        log("info", f"MaterialLoader: reading program from {path}")
        return path.read_text(encoding="utf-8")

    def get_rubrics(self, formation_dir: str) -> Dict:
        """
        Read and parse material/<formation_dir>/rubrics.yaml.
        Raises FileNotFoundError with a clear message if not found.
        """
        path = self.material_root / formation_dir / "rubrics.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"MaterialLoader: rubrics.yaml not found at {path}. "
                f"Check that formation_dir '{formation_dir}' is correct."
            )
        log("info", f"MaterialLoader: reading rubrics from {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
