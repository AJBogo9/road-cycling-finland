import geopandas as gpd
import pytest
from shapely import LineString, Point

from roadcycling.network import CRS
from roadcycling.stations import metro_stations, nearest, rail_stations


def test_rail_keeps_finnish_passenger_stations():
    raw = [
        {
            "stationName": "A",
            "passengerTraffic": True,
            "countryCode": "FI",
            "latitude": 60.1,
            "longitude": 24.4,
        },
        {
            "stationName": "B",
            "passengerTraffic": False,
            "countryCode": "FI",
            "latitude": 60.2,
            "longitude": 24.5,
        },
        {
            "stationName": "C",
            "passengerTraffic": True,
            "countryCode": "RU",
            "latitude": 60.3,
            "longitude": 28.0,
        },
    ]
    got = rail_stations(raw)
    assert got["name"].tolist() == ["A"]
    assert got.crs == CRS


def test_metro_reads_station_rows_only():
    text = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type,vehicle_type\n"
        "1,Kivenlahden metroasema,60.15,24.64,1,1\n"
        "2,Kivenlahti,60.15,24.64,0,1\n"
        "3,Espoon asema,60.2,24.65,1,109\n"
    )
    assert metro_stations(text)["name"].tolist() == ["Kivenlahden metroasema"]


def test_nearest_measures_to_the_closest_point_of_the_segment():
    seg = gpd.GeoDataFrame({"name": ["road"]}, geometry=[LineString([(0, 0), (10000, 0)])], crs=CRS)
    st = gpd.GeoDataFrame(
        {"name": ["by the end", "by the middle"]},
        geometry=[Point(10000, 2000), Point(5000, 3000)],
        crs=CRS,
    )
    out = nearest(seg, st)
    assert out["station_name"].tolist() == ["by the end"]
    assert out["station_km"].tolist() == pytest.approx([2.0])
    assert out["name"].tolist() == ["road"] and len(out) == 1


def test_rail_drops_stations_without_departures():
    raw = [
        {
            "stationName": "Kirkkonummi",
            "stationShortCode": "KKN",
            "passengerTraffic": True,
            "countryCode": "FI",
            "latitude": 60.12,
            "longitude": 24.44,
        },
        {
            "stationName": "Porvoo",
            "stationShortCode": "PRV",
            "passengerTraffic": True,
            "countryCode": "FI",
            "latitude": 60.39,
            "longitude": 25.66,
        },
    ]
    assert rail_stations(raw, served=["KKN"])["name"].tolist() == ["Kirkkonummi"]
