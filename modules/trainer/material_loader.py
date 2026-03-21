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
            log(
                "warning",
                f"MaterialLoader: material root not found: {self.material_root}",
            )
            return []
        return sorted(
            [
                d.name
                for d in self.material_root.iterdir()
                if d.is_dir() and (d / "program.md").exists()
            ]
        )

    def formation_exists(self, formation_dir: str) -> bool:
        """Check if material/<formation_dir>/ exists and has program.md."""
        path = self.material_root / formation_dir
        return path.is_dir() and (path / "program.md").exists()

    def get_program(self, formation_dir: str) -> str:
        """
        Read and return training program as string.

        Supports:
        - Relative paths: "nexoria" → material/nexoria/program.md
        - Absolute paths: "/path/to/file.md" → reads directly
        - Scenarios prefix: "scenarios:nexoria_program.md" → reads from project_root/scenarios/nexoria_program.md

        Raises FileNotFoundError with a clear message if not found.
        """
        path: Optional[Path] = None

        if formation_dir.startswith("scenarios:"):
            # Resolve relative to project root: scenarios:modules/benchmarker/scenarios/file.md
            project_root = self.material_root.parent
            relative_path = formation_dir[len("scenarios:") :]
            path = project_root / relative_path
        elif Path(formation_dir).is_absolute():
            path = Path(formation_dir)
        else:
            path = self.material_root / formation_dir / "program.md"

        if not path.exists():
            raise FileNotFoundError(
                f"MaterialLoader: program not found at {path}. "
                f"Check that formation_dir '{formation_dir}' is correct."
            )
        log("debug", f"MaterialLoader: reading program from {path}")
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
        log("debug", f"MaterialLoader: reading rubrics from {path}")
        with open(path, "r", encoding="utf-8") as f:
            try:
                return yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                log(
                    "warning",
                    f"MaterialLoader: could not parse {path}, returning empty rubrics. Error: {e}",
                )
                return {}
