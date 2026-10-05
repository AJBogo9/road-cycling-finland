"""station points and nearest-station distance"""

import csv
import io

import geopandas as gpd
import pandas as pd

from .network import CRS


def _points(names, lons, lats, kind) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"name": names, "type": kind},
        geometry=gpd.points_from_xy(lons, lats),
        crs="EPSG:4326",
    ).to_crs(CRS)


def rail_stations(raw, served=None) -> gpd.GeoDataFrame:
    """finnish passenger stations, limited to the short codes in served when given"""
    rows = [s for s in raw if s["passengerTraffic"] and s["countryCode"] == "FI"]
    if served is not None:
        served = set(served)
        rows = [s for s in rows if s["stationShortCode"] in served]
    return _points(
        [s["stationName"] for s in rows],
        [s["longitude"] for s in rows],
        [s["latitude"] for s in rows],
        "rail",
    )


def metro_stations(stops_csv) -> gpd.GeoDataFrame:
    rows = [
        r
        for r in csv.DictReader(io.StringIO(stops_csv))
        if r["vehicle_type"] == "1" and r["location_type"] == "1"
    ]
    return _points(
        [r["stop_name"] for r in rows],
        [float(r["stop_lon"]) for r in rows],
        [float(r["stop_lat"]) for r in rows],
        "metro",
    )


def all_stations(raw) -> gpd.GeoDataFrame:
    parts = [
        rail_stations(raw["rail_stations"], raw["rail_stops"]["stations"]),
        metro_stations(raw["hsl_stops"]),
    ]
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=CRS)


def nearest(segments, stations) -> gpd.GeoDataFrame:
    s = stations.to_crs(segments.crs).rename(
        columns={"name": "station_name", "type": "station_type"}
    )
    joined = gpd.sjoin_nearest(
        segments,
        s[["station_name", "station_type", "geometry"]],
        how="left",
        distance_col="station_m",
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    joined["station_km"] = joined.pop("station_m") / 1000
    return joined.drop(columns="index_right")
