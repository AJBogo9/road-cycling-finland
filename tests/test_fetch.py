import io
import zipfile

import pytest

from roadcycling import fetch

BBOX = (60.0, 24.0, 60.5, 25.0)
ALL = [*fetch.LAYERS, "rail_stations", "rail_stops", "hsl_stops"]


def row(code, stopping=True, commercial=True, kind="DEPARTURE"):
    return {
        "stationShortCode": code,
        "type": kind,
        "trainStopping": stopping,
        "commercialStop": commercial,
    }


TRAINS = [
    {"trainCategory": "Commuter", "timeTableRows": [row("KKN"), row("HKI", kind="ARRIVAL")]},
    {"trainCategory": "Long-distance", "timeTableRows": [row("KR"), row("IKO", stopping=False)]},
    {"trainCategory": "Cargo", "timeTableRows": [row("PRV")]},
    {"trainCategory": "Commuter", "timeTableRows": [row("NLÄ", commercial=False)]},
]


class FakeResponse:
    def __init__(self, text="", data=None, content=b""):
        self.text, self._data, self.content = text, data, content

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, matched, features):
        self.matched, self.features, self.calls = matched, features, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        if url == fetch.WFS and params.get("resultType") == "hits":
            return FakeResponse(text=f'<wfs:FeatureCollection numberMatched="{self.matched}"/>')
        if url == fetch.WFS:
            return FakeResponse(data={"type": "FeatureCollection", "features": self.features})
        if url == fetch.DIGITRAFFIC:
            return FakeResponse(data=[{"stationName": "Kirkkonummi"}])
        if url.startswith(fetch.DIGITRAFFIC_TRAINS):
            return FakeResponse(data=TRAINS)
        if url == fetch.HSL_GTFS:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("stops.txt", "﻿stop_id,stop_name\n1,A\n")
            return FakeResponse(content=buf.getvalue())
        raise AssertionError(url)


def test_bbox_is_lat_lon_urn():
    params = fetch.wfs_params("t", BBOX, ["a", "b"])
    assert params["bbox"] == "60.0,24.0,60.5,25.0,urn:ogc:def:crs:EPSG::4326"
    assert params["propertyName"] == "a,b"
    assert fetch.wfs_params("t", BBOX, hits=True)["resultType"] == "hits"


def test_count_mismatch_raises():
    with pytest.raises(fetch.FetchError, match="matched 3 features but sent 2"):
        fetch.fetch_layer(FakeSession(3, [{}, {}]), "tiestotiedot:x", BBOX)


def test_fetch_all_writes_then_uses_cache(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    assert fetch.fetch_all(tmp_path, BBOX, session=session) == ALL
    raw = fetch.load_raw(tmp_path)
    assert raw["hsl_stops"].startswith("stop_id")
    assert raw["fetched"]["bbox"] == list(BBOX)
    calls = len(session.calls)
    assert fetch.fetch_all(tmp_path, BBOX, session=session) == []
    assert len(session.calls) == calls


def test_changed_bbox_fetches_again(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    fetch.fetch_all(tmp_path, BBOX, session=session)
    assert fetch.fetch_all(tmp_path, (60.1, 24.3, 60.2, 24.5), session=session) == ALL


def test_digitraffic_gets_user_header(tmp_path):
    session = FakeSession(1, [{"properties": {}}])
    fetch.fetch_all(tmp_path, BBOX, session=session)
    headers = next(h for url, _, h in session.calls if url == fetch.DIGITRAFFIC)
    assert headers["Digitraffic-User"]


def test_served_stations_need_a_commercial_passenger_departure():
    assert fetch.served_stations(TRAINS) == ["KKN", "KR"]


def test_rail_stops_are_saved_with_their_day(tmp_path):
    fetch.fetch_all(tmp_path, BBOX, session=FakeSession(1, [{"properties": {}}]))
    stops = fetch.load_raw(tmp_path)["rail_stops"]
    assert stops["stations"] == ["KKN", "KR"] and len(stops["date"]) == 10


class FailingSession(FakeSession):
    """fails the feature request for one layer, like a timeout"""

    def __init__(self, fail_type):
        super().__init__(1, [{"properties": {}}])
        self.fail_type = fail_type

    def get(self, url, params=None, headers=None, timeout=None):
        if params and params.get("typeNames") == self.fail_type and "resultType" not in params:
            raise fetch.FetchError("timed out")
        return super().get(url, params=params, headers=headers, timeout=timeout)


def test_interrupted_fetch_after_a_box_change_resumes(tmp_path):
    fetch.fetch_all(tmp_path, BBOX, session=FakeSession(1, [{"properties": {}}]))
    new = (60.1, 24.3, 60.2, 24.5)
    with pytest.raises(fetch.FetchError):
        fetch.fetch_all(tmp_path, new, session=FailingSession("tiestotiedot:liikennemaarat"))
    done = fetch.fetch_all(tmp_path, new, session=FakeSession(1, [{"properties": {}}]))
    assert done == ALL[ALL.index("traffic") :]
