import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from roadcycling import config
from roadcycling.score import components, missing, passes, ramp, score

CFG = config.load(Path(__file__).parents[1] / "config.toml")


def rows(**columns):
    n = len(next(iter(columns.values())))
    base = {
        "speed_limit": [np.nan] * n,
        "kvl": [np.nan] * n,
        "surface": [None] * n,
        "condition": [np.nan] * n,
    }
    return pd.DataFrame({**base, **columns})


def test_ramp_ends_middle_and_clipping():
    assert ramp([50, 75, 100, 30, 120], 50, 100).tolist() == [1, 0.5, 0, 1, 0]
    assert ramp([5, 3, 1], 5, 1).tolist() == [1, 0.5, 0]
    assert np.isnan(ramp([np.nan], 50, 100)[0])


def test_traffic_is_linear_in_log_kvl():
    df = rows(kvl=[200, 3000, math.sqrt(200 * 3000), 50, 10000, 0])
    assert components(df, CFG)["traffic"].tolist() == pytest.approx([1, 0, 0.5, 1, 0, 1])


def test_surface_component():
    df = rows(surface=["asphalt", "soft_asphalt", "gravel", None])
    got = components(df, CFG)["surface"].tolist()
    assert got[:3] == [1.0, 0.7, 0.0] and np.isnan(got[3])


def test_missing_component_rescales_the_weights():
    # traffic 1 * 0.4 + condition 0 * 0.3 + speed 1 * 0.2 + surface 1 * 0.1 = 0.7
    full = rows(kvl=[200], condition=[1], speed_limit=[50], surface=["asphalt"])
    assert score(full, CFG).tolist() == pytest.approx([70])
    # without condition: 0.7 / 0.7
    partial = rows(kvl=[200], speed_limit=[50], surface=["asphalt"])
    assert score(partial, CFG).tolist() == pytest.approx([100])
    assert np.isnan(score(rows(kvl=[np.nan]), CFG)[0])


def test_pass_rules_with_limits_and_missing_values():
    df = rows(
        surface=["asphalt", "soft_asphalt", "gravel", None, "asphalt", "asphalt", "asphalt"],
        speed_limit=[80, 60, 60, 60, 90, 60, 60],
        kvl=[1000, 100, 100, 100, 100, 1001, 100],
        condition=[3, 5, 5, 5, 5, 5, np.nan],
    )
    assert passes(df, CFG).tolist() == [True, True, False, False, False, False, False]
    assert missing(df).tolist() == ["", "", "", "surface", "", "", "condition"]
