import json
import tempfile
from pathlib import Path

from core.config import load_all_configs


def test_config_key_source_file_and_list_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "config.json").write_text(json.dumps({"app": {"name": "T"}}), encoding="utf-8")

        mod = root / "modules" / "x"
        mod.mkdir(parents=True)
        (mod / "config.json").write_text(json.dumps({"x": {"enabled": True}}), encoding="utf-8")
        (mod / "local_config.json").write_text(json.dumps({"x": {"enabled": False}}), encoding="utf-8")

        cfg = load_all_configs(str(root), additional_prefixes=["local"])

        assert cfg.get_key_source_file("x.enabled") is not None
        files = cfg.list_source_files()
        assert len(files) >= 2
        assert any(f.endswith("config.json") for f in files)
