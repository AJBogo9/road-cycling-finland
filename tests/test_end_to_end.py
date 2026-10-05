from pathlib import Path

import pytest

from roadcycling import cli, config, fetch

CFG = config.load(Path(__file__).parents[1] / "config.toml")


@pytest.mark.network
def test_kirkkonummi_box(tmp_path):
    fetch.fetch_all(tmp_path / "raw", (60.10, 24.30, 60.20, 24.50))
    segs = cli.build(CFG, tmp_path / "raw", tmp_path / "segments.gpkg")
    assert len(segs) > 100
    assert segs["passes"].any()
    assert segs["station_km"].max() < 20
