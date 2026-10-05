from pathlib import Path

import pytest

from roadcycling import config

ROOT = Path(__file__).parents[1]


def test_repo_config_loads():
    cfg = config.load(ROOT / "config.toml")
    assert cfg.bbox == (59.75, 22.80, 60.95, 26.60)
    assert cfg.max_speed_limit == 80
    assert cfg.max_kvl == 1000
    assert cfg.traffic.weight == 0.4
    assert cfg.surface_values == {"asphalt": 1.0, "soft_asphalt": 0.7, "gravel": 0.0}


def test_swapped_bbox_raises(tmp_path):
    text = (ROOT / "config.toml").read_text(encoding="utf-8")
    text = text.replace("[59.75, 22.80, 60.95, 26.60]", "[60.95, 22.80, 59.75, 26.60]")
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="bbox"):
        config.load(path)
