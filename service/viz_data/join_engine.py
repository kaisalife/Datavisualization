"""跨源 Join 引擎。

支持把两个 VizDataset 的 tabular 数据按指定条件 Join。

示例场景：
- CRM 客户表 join 订单表（通过 customer_id）
- 用户行为表 join 付费记录（通过 user_id）
- 库存表 join 销售表（通过 product_id）

支持的 Join 类型：
- inner: 只保留两边都匹配的行
- left:  保留左表所有行
- right: 保留右表所有行
- outer: 保留左右两边所有行

使用方式：
1. 直接调用 `join_datasets(left, right, on="key", how="inner")`
2. 或者调用 `join_by_config(datasets, config)`（config 来自请求参数）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TypedDict

import pandas as pd

from service.viz_data.adapters.base import AdapterError
from service.viz_data.schema import DataRef, TabularBlock, VizDataset
from service.viz_data.source_descriptor import SourceDescriptor
from service.viz_data.storage import new_dataset_dir, save_dataframe_to_parquet


class JoinConfig(TypedDict, total=False):
    """Join 配置。"""
    # 左表索引（在 datasets 列表中的位置，默认 0）
    left_idx: int
    # 右表索引（默认 1）
    right_idx: int
    # Join 键：单字符串为两表同名字段，元组为 (left_key, right_key)
    on: str | tuple[str, str]
    # Join 类型：inner / left / right / outer
    how: str
    # 左表字段后缀（如 "_left"，当两表有同名字段时区分，默认 "_left"）
    suffix_left: str
    # 右表字段后缀（默认 "_right"）
    suffix_right: str
    # 是否在 Join 后自动丢弃全空列
    drop_all_nan: bool


_DEFAULT_JOIN_CONFIG: JoinConfig = {
    "left_idx": 0,
    "right_idx": 1,
    "on": "id",
    "how": "inner",
    "suffix_left": "_left",
    "suffix_right": "_right",
    "drop_all_nan": True,
}


def join_datasets(
    left: VizDataset,
    right: VizDataset,
    on: str | tuple[str, str],
    how: str = "inner",
    suffixes: tuple[str, str] = ("_left", "_right"),
    drop_all_nan: bool = True,
) -> VizDataset:
    """Join 两个 VizDataset 的 tabular 数据。

    Args:
        left:  左表
        right: 右表
        on:    Join 键。字符串为同名字段，元组为 (left_key, right_key)
        how:   inner / left / right / outer（与 pandas merge 一致）
        suffixes: 同名冲突时加的后缀（左表后缀，右表后缀）
        drop_all_nan: 是否丢弃结果中全为空的列

    Returns:
        新的 VizDataset，tabular 为 Join 后的结果，
        related_datasets 包含原始的 left/right 作为引用。

    Raises:
        AdapterError: 左表或右表无 tabular 数据，或 Join 键不存在
    """
    if left.tabular is None or left.tabular.data_ref is None:
        raise AdapterError("左数据集没有可 Join 的 tabular 数据")
    if right.tabular is None or right.tabular.data_ref is None:
        raise AdapterError("右数据集没有可 Join 的 tabular 数据")

    # 读取 parquet
    left_df = pd.read_parquet(left.tabular.data_ref.path)
    right_df = pd.read_parquet(right.tabular.data_ref.path)

    # 校验 Join 键
    if isinstance(on, str):
        left_key, right_key = on, on
    else:
        left_key, right_key = on

    if left_key not in left_df.columns:
        raise AdapterError(f"左表中不存在 Join 键 '{left_key}'，可用列: {list(left_df.columns)}")
    if right_key not in right_df.columns:
        raise AdapterError(f"右表中不存在 Join 键 '{right_key}'，可用列: {list(right_df.columns)}")

    # 如果 left_key != right_key，pandas merge 只支持 on= 同名列
    # 需要先 rename 右表的 Join 键与左表一致
    renamed_right_df = right_df
    renamed_right_key = right_key
    if left_key != right_key:
        renamed_right_df = right_df.rename(columns={right_key: left_key})
        renamed_right_key = left_key

    # 执行 Join
    suffix_left, suffix_right = suffixes
    merged_df = left_df.merge(
        renamed_right_df,
        on=left_key,
        how=how,
        suffixes=(suffix_left, suffix_right),
    )

    # 清理全空列
    if drop_all_nan:
        merged_df = merged_df.dropna(axis=1, how="all")

    # 落盘 parquet
    dataset_dir = new_dataset_dir()
    merged_path = dataset_dir / "joined.parquet"
    save_dataframe_to_parquet(merged_df, merged_path)

    # 构建新的 VizDataset
    from service.viz_data.introspection.df_stats import dataframe_to_column_schemas

    columns = dataframe_to_column_schemas(merged_df)
    preview_rows = [merged_df.columns.tolist()] + merged_df.head(10).fillna("").values.tolist()

    tabular = TabularBlock(
        columns=columns,
        row_count=len(merged_df),
        preview_rows=preview_rows,
        data_ref=DataRef(
            kind="parquet",
            path=str(merged_path.resolve()),
            size_bytes=merged_path.stat().st_size,
        ),
    )

    return VizDataset(
        name=f"{left.name}_{right.name}_joined",
        source_kind="joined",
        tabular=tabular,
        related_datasets=[left, right],  # 保存原始表作为引用
        descriptor=SourceDescriptor(
            kind="joined",
            label=f"{left.name} ⟕ {right.name} ({how})",
            logical_id=f"{left.name}_{right.name}_join",
            extra={
                "join_on": on,
                "join_type": how,
                "left_rows": len(left_df),
                "right_rows": len(right_df),
                "result_rows": len(merged_df),
            },
        ),
    )


def join_by_config(
    datasets: list[VizDataset],
    config: JoinConfig | dict,
) -> VizDataset:
    """按配置从列表中选两个表 Join。

    这是更灵活的版本，适用于用户通过 API 传入配置的场景。
    """
    cfg = {**_DEFAULT_JOIN_CONFIG, **config}

    left_idx = int(cfg.get("left_idx", 0))
    right_idx = int(cfg.get("right_idx", 1))

    if left_idx >= len(datasets) or right_idx >= len(datasets):
        raise AdapterError(f"Join 索引超出范围，总共有 {len(datasets)} 个数据集，"
                          f"请求左表 {left_idx}，右表 {right_idx}")

    left = datasets[left_idx]
    right = datasets[right_idx]

    on_raw = cfg.get("on", "id")
    if isinstance(on_raw, str) and "," in on_raw:
        # 兼容 "left_key,right_key" 字符串格式
        parts = [p.strip() for p in on_raw.split(",", 1)]
        on = (parts[0], parts[1])
    else:
        on = on_raw  # type: ignore

    how = cfg.get("how", "inner")
    suffixes = (
        cfg.get("suffix_left", "_left"),
        cfg.get("suffix_right", "_right"),
    )
    drop_all_nan = bool(cfg.get("drop_all_nan", True))

    return join_datasets(
        left=left,
        right=right,
        on=on,
        how=how,
        suffixes=suffixes,
        drop_all_nan=drop_all_nan,
    )


def join_many_sequential(
    datasets: list[VizDataset],
    join_keys: list[str | tuple[str, str]],
    how: str = "inner",
) -> VizDataset:
    """顺序 Join 多个表（链式 Join）。

    例如有 datasets = [A, B, C], join_keys = ["id", "order_id"]
    则执行 (A join B on "id") join C on "order_id"

    Args:
        datasets: 数据集列表（长度至少 2）
        join_keys: Join 键列表（长度 len(datasets) - 1）
        how: 统一使用的 Join 类型

    Raises:
        AdapterError: 列表长度不够或 keys 数量不匹配
    """
    if len(datasets) < 2:
        raise AdapterError("顺序 Join 至少需要两个数据集")
    if len(join_keys) != len(datasets) - 1:
        raise AdapterError(f"Join 键数量应为 {len(datasets) - 1} 个，实际 {len(join_keys)}")

    result = datasets[0]
    for i in range(1, len(datasets)):
        result = join_datasets(
            left=result,
            right=datasets[i],
            on=join_keys[i - 1],
            how=how,
        )

    return result
