"""临时数据存储工具：Parquet（表格） + NPZ（数组）。

目录约定：`temp_datasets/{dataset_id}/`，由 VizDataset.cleanup() 删除。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_temp_root() -> Path:
    """获取临时数据集根目录，可通过环境变量 TEMP_DATASETS_DIR 覆盖。"""
    override = os.getenv("TEMP_DATASETS_DIR")
    if override:
        return Path(override)
    return PROJECT_ROOT / "temp_datasets"


def new_dataset_dir(dataset_id: Optional[str] = None) -> tuple[str, Path]:
    """为一个数据集分配临时目录，返回 (dataset_id, path)。"""
    ds_id = dataset_id or f"ds_{uuid.uuid4().hex[:12]}"
    path = get_temp_root() / ds_id
    path.mkdir(parents=True, exist_ok=True)
    return ds_id, path


def save_dataframe_to_parquet(
    df: pd.DataFrame,
    dataset_dir: Path,
    name: str,
) -> Path:
    """把 DataFrame 落盘为 parquet。返回绝对路径。

    使用 pyarrow 引擎；文件名由 name 决定。
    """
    dataset_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(name)
    out_path = dataset_dir / f"{safe_name}.parquet"

    # 转 object 列为字符串，避免 pyarrow 报 mixed type
    df_to_save = df.copy()
    for col in df_to_save.columns:
        if df_to_save[col].dtype == object:
            df_to_save[col] = df_to_save[col].astype(str)

    df_to_save.to_parquet(str(out_path), engine="pyarrow", index=False)
    return out_path


def save_arrays_to_npz(
    arrays: dict[str, "np.ndarray"],
    dataset_dir: Path,
    name: str,
) -> Path:
    """把命名数组集落盘为 npz。返回绝对路径。"""
    import numpy as np

    dataset_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(name)
    out_path = dataset_dir / f"{safe_name}.npz"
    np.savez(str(out_path), **arrays)
    return out_path


def _safe_filename(name: str) -> str:
    """把名字里不适合文件名的字符替换掉。"""
    keep = "-_.() "
    return "".join(c if c.isalnum() or c in keep else "_" for c in name).strip() or "data"
