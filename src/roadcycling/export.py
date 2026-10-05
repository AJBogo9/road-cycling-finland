"""write the files the site reads"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

from . import score

SITE_COLUMNS = [
    "tie",
    "osa",
    "name",
    "speed_limit",
    "kvl",
    "kvl_year",
    "surface",
    "condition",
    "score",
    "passes",
    "station_name",
    "station_type",
    "station_km",
    "length_m",
    "geometry",
]

# what a reader sees on the map; touching segments that agree on all of it merge into one
LOOK = [
    "tie",
    "osa",
    "name",
    "speed_limit",
    "kvl",
    "kvl_year",
    "surface",
    "condition",
    "score",
    "passes",
    "station_name",
    "station_type",
]
SIMPLIFY_M = 2.0


def merge_runs(segments) -> gpd.GeoDataFrame:
    s = segments.sort_values(["tie", "osa", "ajorata", "aet"]).reset_index(drop=True)
    # the map filters station distance in whole km, so a run stays inside one band
    key = s[[*LOOK, "ajorata"]].assign(station_band=np.ceil(s["station_km"]))
    prev = key.shift()
    # two missing values count as equal
    equal = (key == prev) | (key.isna() & prev.isna())
    same = equal.all(axis=1) & (s["aet"] == s["let"].shift())
    run = (~same).cumsum()
    groups = s.groupby(run)
    looks = groups[LOOK].first()
    sums = groups.agg(station_km=("station_km", "min"), length_m=("length_m", "sum"))
    geometry = groups["geometry"].agg(
        lambda g: shapely.line_merge(shapely.multilinestrings(shapely.get_parts(g.values)))
    )
    return gpd.GeoDataFrame(
        looks.join(sums), geometry=geometry.values, crs=segments.crs
    ).reset_index(drop=True)


def _geojson(gdf, path: Path) -> None:
    path.unlink(missing_ok=True)
    gdf.to_crs(4326).to_file(
        path, driver="GeoJSON", engine="pyogrio", RFC7946="YES", COORDINATE_PRECISION=5
    )


def to_site(segments, stations, cfg, out_dir, fetched_on) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # recompute with the current thresholds, so the map matches the rule text in meta.json
    seg = score.apply(segments, cfg)
    seg["score"] = seg["score"].round()
    seg = merge_runs(seg)
    seg["geometry"] = seg.geometry.simplify(SIMPLIFY_M)
    # round up to 0.1 km, so the map's whole-km distance filter matches the per-segment one;
    # the inner round drops float noise such as 1.2 * 10 = 12.000000000000002
    seg["station_km"] = np.ceil((seg["station_km"] * 10).round(6)) / 10
    seg["length_m"] = seg["length_m"].round()
    _geojson(seg[SITE_COLUMNS], out / "segments.geojson")

    south, west, north, east = cfg.bbox
    near = stations.to_crs(4326).cx[west:east, south:north]
    _geojson(near[["name", "type", "geometry"]], out / "stations.geojson")

    passing = seg.loc[seg["passes"], "score"]
    meta = {
        "fetched": fetched_on,
        # lowest passing score rounded down to 5, where the map's colour ramp starts
        "score_floor": int(passing.min() // 5 * 5) if len(passing) else 0,
        "bbox": list(cfg.bbox),
        "max_station_km": cfg.max_station_km,
        "filters": {
            "surfaces": list(cfg.surfaces),
            "max_speed_limit": cfg.max_speed_limit,
            "max_kvl": cfg.max_kvl,
            "min_condition": cfg.min_condition,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
