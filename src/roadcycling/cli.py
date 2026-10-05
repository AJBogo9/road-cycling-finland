"""roadcycling fetch | build | export"""

import argparse
from pathlib import Path

import geopandas as gpd

from . import config, export, fetch, network, score, stations

RAW = Path("data/raw")
SEGMENTS = Path("data/processed/segments.gpkg")
SITE_DATA = Path("site/data")


def build(cfg, raw_dir=RAW, out=SEGMENTS) -> gpd.GeoDataFrame:
    raw = fetch.load_raw(raw_dir)
    points = stations.all_stations(raw)
    segs = network.clip_to_bbox(network.build_segments(raw), cfg.bbox)
    segs = score.apply(segs, cfg)
    segs = stations.nearest(segs, points)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    segs.to_file(out, layer="segments", driver="GPKG", engine="pyogrio")
    points.to_file(out, layer="stations", driver="GPKG", engine="pyogrio")
    return segs


def export_site(cfg, segments_path=SEGMENTS, raw_dir=RAW, site_dir=SITE_DATA) -> None:
    if not Path(segments_path).exists():
        # pyogrio raises its own error type for a missing file
        raise FileNotFoundError(2, "No such file", str(segments_path))
    segs = gpd.read_file(segments_path, layer="segments")
    points = gpd.read_file(segments_path, layer="stations")
    fetched = fetch.load_raw_log(raw_dir)
    export.to_site(segs, points, cfg, site_dir, min(fetched["layers"].values()))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="roadcycling", description="Score Finnish state roads for road cycling."
    )
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download layers and stations into data/raw/")
    f.add_argument("--refresh", action="store_true", help="download again even if cached")
    sub.add_parser("build", help="join and score into data/processed/segments.gpkg")
    sub.add_parser("export", help="write site/data/ for the map")
    args = parser.parse_args(argv)
    cfg = config.load(args.config)
    try:
        if args.command == "fetch":
            done = fetch.fetch_all(RAW, cfg.bbox, refresh=args.refresh)
            print("fetched:", ", ".join(done) if done else "nothing, all cached")
        elif args.command == "build":
            segs = build(cfg)
            km = segs["length_m"].sum() / 1000
            ok = segs.loc[segs["passes"], "length_m"].sum() / 1000
            print(f"{len(segs)} segments, {km:.0f} km, {ok:.0f} km pass, written to {SEGMENTS}")
        elif args.command == "export":
            export_site(cfg)
            print(f"wrote {SITE_DATA}/")
    except FileNotFoundError as e:
        step = "roadcycling build" if args.command == "export" else "roadcycling fetch"
        raise SystemExit(f"missing {e.filename}: run `{step}` first") from None
