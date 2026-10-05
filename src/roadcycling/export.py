"""write the files the site reads"""

import json
from pathlib import Path

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


def _geojson(gdf, path: Path) -> None:
    path.unlink(missing_ok=True)
    gdf.to_crs(4326).to_file(
        path, driver="GeoJSON", engine="pyogrio", RFC7946="YES", COORDINATE_PRECISION=5
    )


def to_site(segments, stations, cfg, out_dir, fetched_on) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seg = segments[SITE_COLUMNS].copy()
    seg["score"] = seg["score"].round()
    seg["station_km"] = seg["station_km"].round(1)
    seg["length_m"] = seg["length_m"].round()
    _geojson(seg, out / "segments.geojson")

    south, west, north, east = cfg.bbox
    near = stations.to_crs(4326).cx[west:east, south:north]
    _geojson(near[["name", "type", "geometry"]], out / "stations.geojson")

    meta = {
        "fetched": fetched_on,
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
