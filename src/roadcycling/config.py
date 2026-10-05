"""load and validate config.toml"""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Ramp:
    best: float
    worst: float
    weight: float


@dataclass(frozen=True)
class Config:
    bbox: tuple[float, float, float, float]  # south, west, north, east
    surfaces: tuple[str, ...]
    max_speed_limit: float
    max_kvl: float
    min_condition: float
    traffic: Ramp
    condition: Ramp
    speed_limit: Ramp
    surface_weight: float
    surface_values: dict[str, float]
    max_station_km: float


def load(path: str | Path = "config.toml") -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    south, west, north, east = raw["area"]["bbox"]
    if not (south < north and west < east):
        raise ValueError(f"bbox must be [south, west, north, east], got {raw['area']['bbox']}")
    filters, score = raw["filters"], raw["score"]
    ramps = {name: Ramp(**score[name]) for name in ("traffic", "condition", "speed_limit")}
    for name, ramp in ramps.items():
        if ramp.best == ramp.worst:
            raise ValueError(f"score.{name}: best and worst must differ")
    surface_values = dict(score["surface"])
    surface_weight = surface_values.pop("weight")
    weights = [r.weight for r in ramps.values()] + [surface_weight]
    if min(weights) < 0 or sum(weights) <= 0:
        raise ValueError(f"weights must be non-negative with a positive sum, got {weights}")
    return Config(
        bbox=(south, west, north, east),
        surfaces=tuple(filters["surfaces"]),
        max_speed_limit=filters["max_speed_limit"],
        max_kvl=filters["max_kvl"],
        min_condition=filters["min_condition"],
        surface_weight=surface_weight,
        surface_values=surface_values,
        max_station_km=raw["site"]["max_station_km"],
        **ramps,
    )
