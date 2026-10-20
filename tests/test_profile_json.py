"""数据预览 / 统计必须是标准 JSON（不允许 NaN / Infinity）。"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd

from service.data_ingestion.profiler import build_profile_from_df


def test_profile_preview_and_stats_are_standard_json():
    df = pd.DataFrame(
        {
            "值": [1.0, float("nan"), float("inf"), -np.inf],
            "时间": pd.to_datetime(["2024-01-01", None, "2024-01-03", "2024-01-04"]),
            "名称": ["a", None, "c", "d"],
        }
    )

    # inf 参与统计时 numpy 会发 RuntimeWarning，这里故意构造非法值，忽略即可
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        profile = build_profile_from_df(df, "t", "file", "x")
    payload = profile.to_prompt_dict()

    # allow_nan=False：NaN / Infinity 还没清理干净就会直接抛 ValueError
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    assert "Infinity" not in text
    assert "NaN" not in text
    assert payload["preview"][1]["值"] is None
    assert payload["preview"][2]["值"] is None
    assert payload["preview"][3]["值"] is None
    assert payload["preview"][0]["时间"].startswith("2024-01-01")
    assert payload["stats"]["值"]["max"] is None
