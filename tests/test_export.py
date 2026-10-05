import geopandas as gpd
import numpy as np
import pytest
from shapely import LineString

from roadcycling.export import merge_runs
from roadcycling.network import CRS


def segments(rows):
    keys = ["tie", "osa", "ajorata", "aet", "let", "condition", "station_km"]
    data = {k: [r[i] for r in rows] for i, k in enumerate(keys)}
    base = {
        "name": "Testitie",
        "speed_limit": 60.0,
        "kvl": np.nan,
        "kvl_year": np.nan,
        "surface": "asphalt",
        "score": 70.0,
        "passes": True,
        "station_name": "Kirkkonummi",
        "station_type": "rail",
    }
    geoms = [LineString([(r[3], 0), (r[4], 0)]) for r in rows]
    gdf = gpd.GeoDataFrame({**data, **base}, geometry=geoms, crs=CRS)
    gdf["length_m"] = gdf.length
    return gdf


def test_merge_runs_joins_touching_segments_that_look_the_same():
    segs = segments(
        [
            (1, 1, 0, 0, 100, 4, 3.0),
            (1, 1, 0, 100, 200, 4, 2.5),  # same look, touches: merges
            (1, 1, 0, 200, 300, 3, 2.4),  # condition differs: new run
            (1, 1, 0, 350, 400, 3, 2.4),  # gap before it: new run
            (1, 2, 0, 0, 100, 3, 2.4),  # next part: new run
        ]
    )
    out = merge_runs(segs)
    assert len(out) == 4
    first = out.iloc[0]
    assert first["length_m"] == pytest.approx(200)
    assert first["station_km"] == pytest.approx(2.5)
    assert first.geometry.geom_type == "LineString" and first.geometry.length == pytest.approx(200)


def test_merge_runs_treats_two_missing_values_as_equal():
    segs = segments([(1, 1, 0, 0, 100, np.nan, 1.0), (1, 1, 0, 100, 200, np.nan, 1.0)])
    assert len(merge_runs(segs)) == 1


def test_merge_runs_keeps_whole_km_station_bands_apart():
    # the map filters station distance in whole km, so a run must not span two bands
    segs = segments(
        [(1, 1, 0, 0, 100, 4, 0.4), (1, 1, 0, 100, 200, 4, 0.9), (1, 1, 0, 200, 300, 4, 1.6)]
    )
    out = merge_runs(segs)
    assert out["station_km"].tolist() == pytest.approx([0.4, 1.6])


def test_to_site_rounds_station_distance_up(tmp_path):
    # 15.04 km must not pass a "within 15 km" filter on the map
    import json
    from pathlib import Path

    from shapely import Point

    from roadcycling import config
    from roadcycling.export import to_site

    cfg = config.load(Path(__file__).parents[1] / "config.toml")
    segs = segments([(1, 1, 0, 361000, 361100, 4, 15.04)])
    segs = segs.set_geometry([LineString([(361000, 6670000), (361100, 6670000)])], crs=CRS)
    st = gpd.GeoDataFrame(
        {"name": ["X"], "type": ["rail"]}, geometry=[Point(361000, 6670000)], crs=CRS
    )
    to_site(segs, st, cfg, tmp_path, "2026-10-05")
    props = json.loads((tmp_path / "segments.geojson").read_text())["features"][0]["properties"]
    assert props["station_km"] == 15.1
