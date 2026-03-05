"""Unit tests for rubric loader utilities."""

from modules.mem_bench.rubric_loader import find_rubrics, load_rubric


def test_find_rubrics_returns_dict_for_missing_dir(tmp_path):
    missing = tmp_path / "none"
    assert find_rubrics(str(missing)) == {}


def test_load_rubric_returns_empty_on_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("[", encoding="utf-8")
    assert load_rubric(str(bad)) == {}
