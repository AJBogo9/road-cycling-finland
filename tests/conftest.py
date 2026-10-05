import pytest


def feature(props, geometry=None):
    return {"type": "Feature", "properties": props, "geometry": geometry}


def address(tie, aosa, aet, losa, let):
    return {
        "alkusijainti_tie": tie,
        "alkusijainti_osa": aosa,
        "alkusijainti_etaisyys": aet,
        "loppusijainti_tie": tie,
        "loppusijainti_osa": losa,
        "loppusijainti_etaisyys": let,
    }


def xyzm(points):
    return {"type": "LineString", "coordinates": [[x, y, 0, m] for x, y, m in points]}


@pytest.fixture
def synthetic_raw():
    """one 1 km road part near Kirkkonummi; carriageway 2 must be dropped"""
    x0, y0 = 361000, 6670000
    road = {"tie": 1, "osa": 1, "nimi": "Testitie", "ajr_pituus": 1000}
    return {
        "network": {
            "features": [
                feature({**road, "ajorata": 0}, xyzm([(x0, y0, 0), (x0 + 1000, y0, 1000)])),
                feature(
                    {**road, "ajorata": 2}, xyzm([(x0, y0 + 30, 0), (x0 + 1000, y0 + 30, 1000)])
                ),
            ]
        },
        "speed": {
            "features": [
                feature(
                    {
                        **address(1, 1, 0, 1, 1000),
                        "nopeusrajoitus": "60",
                        "sijaintitarkenne_puoli": "Oikea",
                    }
                )
            ]
        },
        "traffic": {
            "features": [
                feature(
                    {
                        **address(1, 1, 0, 1, 1000),
                        "kvl": 400,
                        "laskentavuosi": 2024,
                        "laskentatarkkuus": "8 % virhemarginaali",
                    }
                )
            ]
        },
        "pavement": {
            "features": [
                feature(
                    {
                        **address(1, 1, 0, 1, 400),
                        "tyyppi": "Kulutuskerros",
                        "paallysteen_tyyppi": "Pehmeät asfalttibetonit (PAB-B)",
                    }
                ),
                feature(
                    {
                        **address(1, 1, 0, 1, 1000),
                        "tyyppi": "Alempi päällystekerros 2",
                        "paallysteen_tyyppi": "Asfalttibetoni",
                    }
                ),
            ]
        },
        "gravel": {"features": []},
        "condition": {
            "features": [
                feature(
                    {
                        "tie": 1,
                        "ajr": 0,
                        "kaista": 11,
                        "aosa": 1,
                        "aet": 0,
                        "losa": 1,
                        "let": 1000,
                        "kunto_lk_nro": 4,
                        "tas": 1.5,
                        "ura": 3.0,
                    }
                )
            ]
        },
        "rail_stations": [
            {
                "stationName": "Kirkkonummi",
                "passengerTraffic": True,
                "countryCode": "FI",
                "latitude": 60.119648,
                "longitude": 24.438814,
            }
        ],
        "hsl_stops": "stop_id,stop_name,stop_lat,stop_lon,location_type,vehicle_type\n"
        "1,Kivenlahden metroasema,60.1513,24.6338,1,1\n",
        "fetched": {"bbox": [59.75, 22.8, 60.95, 26.6], "layers": {"network": "2026-10-05"}},
    }
