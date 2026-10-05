import json
from pathlib import Path

import pytest

from roadcycling import cli, config

CFG = config.load(Path(__file__).parents[1] / "config.toml")


def write_raw(raw, raw_dir):
    raw_dir.mkdir()
    for name, data in raw.items():
        if name == "hsl_stops":
            (raw_dir / "hsl_stops.txt").write_text(data, encoding="utf-8")
        else:
            (raw_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_build_then_export(synthetic_raw, tmp_path):
    write_raw(synthetic_raw, tmp_path / "raw")
    gpkg = tmp_path / "processed" / "segments.gpkg"
    segs = cli.build(CFG, tmp_path / "raw", gpkg)
    # 0 to 400 is soft asphalt and passes; 400 to 1000 has no wearing course and fails
    assert segs["passes"].tolist() == [True, False]
    cli.export_site(CFG, gpkg, tmp_path / "raw", tmp_path / "site")
    data = json.loads((tmp_path / "site" / "segments.geojson").read_text())
    props = data["features"][0]["properties"]
    assert props["station_name"] == "Kirkkonummi"
    assert props["passes"] is True
    x, y = data["features"][0]["geometry"]["coordinates"][0]
    assert 24 < x < 25 and 60 < y < 61 and round(x, 5) == x
    meta = json.loads((tmp_path / "site" / "meta.json").read_text())
    assert meta["max_station_km"] == 15 and meta["fetched"] == "2026-10-05"
    names = [
        f["properties"]["name"]
        for f in json.loads((tmp_path / "site" / "stations.geojson").read_text())["features"]
    ]
    assert names == ["Kirkkonummi", "Kivenlahden metroasema"]


def test_build_without_fetch_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        (Path(__file__).parents[1] / "config.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="roadcycling fetch"):
        cli.main(["build"])
