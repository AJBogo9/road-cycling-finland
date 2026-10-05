import numpy as np
import pandas as pd
import pytest

from roadcycling.network import (
    build_segments,
    cut_by_m,
    on_part,
    split_part,
    surface_class,
)


def line(xs, ms):
    """straight line along the x axis with the given m values"""
    return np.column_stack([xs, np.zeros(len(xs)), ms]).astype(float)


def test_surface_class():
    assert surface_class("Asfalttibetoni") == "asphalt"
    assert surface_class("Kantavan kerroksen asfalttibetoni (ABK)") == "asphalt"
    assert surface_class("Pehmeät asfalttibetonit (PAB-O)") == "soft_asphalt"
    assert surface_class("Ei tietoa") is None
    assert surface_class(None) is None


def test_cut_by_m_interpolates_inside_one_line():
    g = cut_by_m([line([0, 100], [0, 100])], 20, 50)
    assert list(g.coords) == [(20, 0), (50, 0)]


def test_cut_by_m_follows_m_not_position():
    # like road 11269 part 1: the single carriageway starts at address 1088
    g = cut_by_m([line([0, 1000], [1088, 2088])], 1088, 1333)
    assert g.length == pytest.approx(245)
    assert g.coords[0] == (0, 0)


def test_cut_by_m_handles_reversed_lines_and_gaps():
    lines = [line([300, 200], [100, 0]), line([500, 600], [150, 250])]
    g = cut_by_m(lines, 50, 200)
    assert g.geom_type == "MultiLineString"
    assert g.length == pytest.approx(100)
    assert cut_by_m(lines, 110, 140) is None


def test_on_part_cuts_an_interval_spanning_two_parts():
    df = pd.DataFrame({"tie": [1], "aosa": [1], "aet": [800], "losa": [2], "let": [300]})
    assert on_part(df, 1, 0, 1000)[["start", "end"]].values.tolist() == [[800, 1000]]
    assert on_part(df, 2, 0, 700)[["start", "end"]].values.tolist() == [[0, 300]]
    assert on_part(df, 3, 0, 500).empty


def test_on_part_clips_to_an_offset_feature():
    df = pd.DataFrame({"tie": [1], "aosa": [1], "aet": [795], "losa": [1], "let": [1333]})
    assert on_part(df, 1, 1088, 5897)[["start", "end"]].values.tolist() == [[1088, 1333]]


def frame(**columns):
    return pd.DataFrame(columns)


def test_split_part_cuts_at_every_end_and_keeps_the_worse_value():
    layers = {
        "speed": frame(start=[0, 0], end=[600, 1000], speed_limit=[50, 40]),
        "traffic": frame(start=[200], end=[1000], kvl=[300], kvl_year=[2024]),
        "surface": frame(
            start=[0, 0], end=[1000, 500], surface=["asphalt", "gravel"], surface_rank=[0, 2]
        ),
        "condition": frame(start=[0, 0], end=[500, 500], condition=[4, 2]),
    }
    seg = split_part(0, 1000, layers)
    assert seg[["aet", "let"]].values.tolist() == [[0, 200], [200, 500], [500, 600], [600, 1000]]
    assert seg["speed_limit"].tolist() == [50, 50, 50, 40]
    assert np.isnan(seg["kvl"][0]) and seg["kvl"][1:].tolist() == [300, 300, 300]
    assert seg["kvl_year"][1:].tolist() == [2024, 2024, 2024]
    assert seg["surface"].tolist() == ["gravel", "gravel", "asphalt", "asphalt"]
    assert seg["condition"][:2].tolist() == [2, 2] and seg["condition"][2:].isna().all()


def test_build_segments_end_to_end(synthetic_raw):
    segs = build_segments(synthetic_raw)
    assert segs.crs == "EPSG:3067"
    assert (segs["ajorata"] == 0).all()
    assert segs[["aet", "let"]].values.tolist() == [[0, 400], [400, 1000]]
    assert segs["surface"].iloc[0] == "soft_asphalt" and pd.isna(segs["surface"].iloc[1])
    assert segs["speed_limit"].tolist() == [60, 60]
    assert segs["kvl"].tolist() == [400, 400]
    assert segs["condition"].tolist() == [4, 4]
    assert segs["name"].tolist() == ["Testitie", "Testitie"]
    assert segs["length_m"].tolist() == pytest.approx([400, 600])


def test_build_segments_with_empty_layers(synthetic_raw):
    synthetic_raw["traffic"] = {"features": []}
    synthetic_raw["pavement"] = {"features": []}
    segs = build_segments(synthetic_raw)
    assert segs[["aet", "let"]].values.tolist() == [[0, 1000]]
    assert segs["kvl"].isna().all() and segs["surface"].isna().all()


def test_clip_to_bbox_drops_segments_outside_the_box():
    import geopandas as gpd
    from shapely import LineString

    from roadcycling.network import CRS, clip_to_bbox

    # two short segments in EPSG:3067: one near Kirkkonummi (60.15 N), one near Hämeenlinna (61.0 N)
    segs = gpd.GeoDataFrame(
        {"tie": [1, 3]},
        geometry=[
            LineString([(361000, 6670000), (362000, 6670000)]),
            LineString([(357000, 6765000), (358000, 6765000)]),
        ],
        crs=CRS,
    )
    kept = clip_to_bbox(segs, (59.75, 22.80, 60.95, 26.60))
    assert kept["tie"].tolist() == [1]


def test_network_parts_keep_road_numbers_below_20000(synthetic_raw):
    from roadcycling.network import network_parts

    ramp = dict(synthetic_raw["network"]["features"][0])
    ramp["properties"] = {**ramp["properties"], "tie": 21408}
    path = dict(synthetic_raw["network"]["features"][0])
    path["properties"] = {**path["properties"], "tie": 70164}
    synthetic_raw["network"]["features"] += [ramp, path]
    assert [p["tie"] for p in network_parts(synthetic_raw["network"])] == [1]
