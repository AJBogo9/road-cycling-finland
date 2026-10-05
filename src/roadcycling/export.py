"""write the files the site reads"""

import json
from pathlib import Path

import geopandas as gpd
import shapely

from . import score

# what the popup shows; touching segments that agree on all of it merge into one
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
    "station_name",
]
SITE_COLUMNS = [*LOOK, "station_km", "length_m", "geometry"]
SIMPLIFY_M = 2.0


def merge_runs(segments) -> gpd.GeoDataFrame:
    s = segments.sort_values(["tie", "osa", "ajorata", "aet"]).reset_index(drop=True)
    key = s[[*LOOK, "ajorata"]]
    prev = key.shift()
    # two missing values count as equal
    equal = (key == prev) | (key.isna() & prev.isna())
    run = (~(equal.all(axis=1) & (s["aet"] == s["let"].shift()))).cumsum()
    groups = s.groupby(run)
    sums = groups.agg(station_km=("station_km", "min"), length_m=("length_m", "sum"))
    geometry = groups["geometry"].agg(
        lambda g: shapely.line_merge(shapely.multilinestrings(shapely.get_parts(g.values)))
    )
    merged = groups[LOOK].first().join(sums)
    return gpd.GeoDataFrame(merged, geometry=geometry.values, crs=segments.crs).reset_index(
        drop=True
    )


def _geojson(gdf, path: Path) -> None:
    path.unlink(missing_ok=True)
    if gdf.empty:
        # geopandas will not write an empty frame
        path.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
        return
    gdf.to_crs(4326).to_file(
        path, driver="GeoJSON", engine="pyogrio", RFC7946="YES", COORDINATE_PRECISION=5
    )


def to_site(segments, stations, cfg, out_dir, fetched_on) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # score with the current thresholds, so the map matches the summary built from meta.json
    seg = score.apply(segments, cfg)
    seg = seg[seg["passes"]].assign(score=lambda d: d["score"].round())
    if not seg.empty:
        seg = merge_runs(seg)
        seg["geometry"] = seg.geometry.simplify(SIMPLIFY_M)
    seg = seg.assign(station_km=seg["station_km"].round(1), length_m=seg["length_m"].round(1))
    _geojson(seg[SITE_COLUMNS], out / "segments.geojson")

    south, west, north, east = cfg.bbox
    near = stations.to_crs(4326).cx[west:east, south:north]
    _geojson(near[["name", "geometry"]], out / "stations.geojson")

    meta = {
        "fetched": fetched_on,
        "bbox": list(cfg.bbox),
        # lowest score on the map rounded down to 5, where the colour ramp starts
        "score_floor": int(seg["score"].min() // 5 * 5) if len(seg) else 0,
        "filters": {
            "surfaces": list(cfg.surfaces),
            "max_speed_limit": cfg.max_speed_limit,
            "max_kvl": cfg.max_kvl,
            "min_condition": cfg.min_condition,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
