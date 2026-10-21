"""Series 拆分器（v4 核心启发式）。

把一张原始表（DataFrame）拆成多个面向可视化的语义 series，每个写入一个 .parquet，
汇总 manifest.json，产出 SeriesCatalog。

拆分优先级（每级带守卫，不满足则降到下一级）：
1. 宽表-时间列（指标×年份/月等，>=2 时间列头 + 少行）-> 每指标一条时间序列
2. 宽表-指标列（一时间列 + >=2 指标列，最常见）-> 每指标一条时间序列
3. 长表（时间/类别 + 值）-> 一条时间序列或类别比较序列
4. 普通 维度+指标 -> 一条类别比较序列
5. 兜底 -> 永远产出整表 generic series（不丢信息）
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from service.data_ingestion.models import RawTable
from service.data_ingestion.profiler import _infer_column_semantics, _is_time_label
from service.data_ingestion.series.models import SemanticSeries, SeriesCatalog
from service.data_ingestion.series.shape import compute_series_shape

# 时间列构造的 melt 产物用固定的行/值列名（避免与业务列冲突）
_TIME_LABEL_COL = "时间"
_VALUE_LABEL_COL = "值"

# 宽表-时间列 判定参数（时间列头由 _is_time_label 识别）
_WIDE_TIME_HINT_MAX_ROWS = 60     # 宽表-时间列 判定：行数上限
_WIDE_TIME_MIN_TIME_HEADS = 3     # 宽表-时间列 判定：最少时间列头数
_WIDE_TIME_TIME_FRACTION = 0.5    # 时间列头占比下限

# 长表「时间 + 维度 + 指标」透视：类别太多时不画多条折线，改为聚合排行
_PIVOT_MAX_CATEGORIES = 12
_CATEGORY_AGG_LIMIT = 20

# 这些指标做跨时间聚合时取平均，其余求和
_AVERAGE_HINTS = ("率", "占比", "比例", "平均", "均值", "单价", "价格", "温度", "评分", "得分", "时长")


def _measure_agg(measure: str) -> str:
    """按指标名猜测跨时间聚合方式（率/均价取平均，其余求和）。"""
    name = str(measure)
    return "mean" if any(hint in name for hint in _AVERAGE_HINTS) else "sum"


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG_UNITS = {"万": 10_000, "亿": 100_000_000}
_CN_NUMERAL_RUN = re.compile(r"[零〇一二三四五六七八九两十百千万亿]+")
_CN_TIME_SUFFIXES = ("月", "季度", "季", "周", "星期", "年", "日", "号")


def _cn_number_to_int(text: str) -> int | None:
    """把中文数字转成整数（支持逐位年份、十/百/千/万/亿）。"""
    if not text:
        return None
    if all(ch in _CN_DIGITS for ch in text):
        # 「二零二四」「〇八」这类逐位写法
        return int("".join(str(_CN_DIGITS[ch]) for ch in text))

    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_SMALL_UNITS:
            if number == 0:
                number = 1
            section += number * _CN_SMALL_UNITS[ch]
            number = 0
        elif ch in _CN_BIG_UNITS:
            unit = _CN_BIG_UNITS[ch]
            section += number
            number = 0
            if unit == 10_000:
                total += section * unit
                section = 0
            else:
                total = (total + section) * unit
                section = 0
        else:
            return None
    return total + section + number


def _natural_key(value) -> str:
    """自然排序键：1月 < 2月 < 10月，一月 < 二月 < 十一月，Q1 < Q2 < Q10。

    中文数字只在「时间标签 / 序数 / 逐位年份」上下文里展开，避免把
    「统一」「万一」这类普通词也改写成数字（排序键只影响顺序，不改数据）。
    """
    text = str(value)

    def _replace(match: re.Match) -> str:
        run = match.group(0)
        start, end = match.start(), match.end()
        prev = text[start - 1] if start > 0 else ""
        nxt = text[end : end + 2]
        is_time = nxt.startswith(_CN_TIME_SUFFIXES)
        is_ordinal = prev == "第"
        is_weekday = prev == "周" or text[max(0, start - 2) : start] == "星期"
        is_digit_year = len(run) >= 2 and all(ch in _CN_DIGITS for ch in run)
        if not (is_time or is_ordinal or is_weekday or is_digit_year):
            return run
        number = _cn_number_to_int(run)
        return f"{number:010d}" if number is not None else run

    text = _CN_NUMERAL_RUN.sub(_replace, text)
    return re.sub(r"\d+", lambda m: m.group(0).zfill(10), text)


def _split_long_with_dimension(
    df: pd.DataFrame, column_semantics: dict[str, str]
) -> list[tuple]:
    """启发式2：长表含 时间 + 维度 + 指标。

    典型形态 ``城市 / 月份 / 销售额``：

    - 类别数 ≤12：透视成「时间 × 类别」宽表，一条 series 画多条折线
      （row_label=月份，column_labels=城市）；
    - 类别数 >12：按维度聚合为排行，避免几十条折线糊在一起。

    多个指标时每个指标一条 series；多个维度时选基数最小（且 ≥2）的那一维。
    """
    time_cols = [c for c, r in column_semantics.items() if r == "time"]
    measure_cols = [c for c, r in column_semantics.items() if r == "measure"]
    dim_cols = [c for c, r in column_semantics.items() if r == "dimension"]
    if len(time_cols) != 1 or not measure_cols or not dim_cols:
        return []

    time_col = time_cols[0]
    cardinalities = {c: int(df[c].nunique(dropna=True)) for c in dim_cols}
    candidates = [c for c, n in cardinalities.items() if 2 <= n <= _PIVOT_MAX_CATEGORIES]
    if candidates:
        dim_col = min(candidates, key=lambda c: cardinalities[c])
    else:
        # 所有维度都只有 1 个值，或都超过阈值
        dim_col = min(cardinalities, key=lambda c: cardinalities[c])
    n_categories = cardinalities[dim_col]
    if n_categories < 2:
        return []  # 交给「单时间 + 指标」启发式

    if n_categories > _PIVOT_MAX_CATEGORIES:
        # 高基数维度：聚合为类别排行（每个指标取合适的聚合方式）
        agg_map = {m: _measure_agg(m) for m in measure_cols}
        ranked = (
            df.groupby(dim_col, as_index=False, dropna=False)[measure_cols]
            .agg(agg_map)
            .sort_values(measure_cols[0], ascending=False)
            .head(_CATEGORY_AGG_LIMIT)
        )
        return [(
            "categorical_comparison", dim_col, list(measure_cols), ranked,
            _sanitize_series_name(dim_col),
            f"{dim_col} 维度的指标汇总（{', '.join(measure_cols)}）",
        )]

    out: list[tuple] = []
    time_values: list = []
    seen_times: set[str] = set()
    for value in df[time_col].dropna():
        label = str(value)
        if label not in seen_times:
            seen_times.add(label)
            time_values.append(value)
    time_order = sorted(time_values, key=_natural_key)
    category_order = list(dict.fromkeys(str(v) for v in df[dim_col].dropna()))

    for measure in measure_cols:
        pivot = df.pivot_table(
            index=time_col,
            columns=dim_col,
            values=measure,
            aggfunc=_measure_agg(measure),
            dropna=False,
        )
        pivot = pivot.reindex(time_order)
        pivot.columns = [
            f"{col}_" if str(col) == str(time_col) else str(col)
            for col in pivot.columns
        ]
        renamed_order = [
            f"{c}_" if c == str(time_col) else c for c in category_order
        ]
        pivot = pivot.reindex(columns=[c for c in renamed_order if c in pivot.columns])
        pivot = pivot.reset_index()
        out.append((
            "time_series", time_col, list(pivot.columns[1:]), pivot,
            _sanitize_series_name(f"{measure} 按{dim_col}"),
            f"不同{dim_col}的{measure}随{time_col}的变化",
        ))
    return out


def _time_header_cols(df: pd.DataFrame) -> list[str]:
    """列名是「时间标签」的列（用于判定 指标×时间 宽表）。

    只看列名：``2020 年`` / ``1 月`` / ``order_date`` 算，``2023 年_销售额``
    这种「时间词 + 指标名」不算，否则会把不同指标误当成时间点。
    """
    return [c for c in df.columns if _is_time_label(c)]


def _safe_filename(name: str) -> str:
    """把系列名转为文件系统安全的分段名（保留中文，仅剔除路径分隔/控制字符）。"""
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    base = re.sub(r"\s+", "_", base).strip("_")
    return base or "series"


def _sanitize_series_name(name: str, limit: int = 60) -> str:
    """精简系列名，保持可读。"""
    name = str(name).strip()
    if len(name) > limit:
        name = name[: limit - 1] + "…"
    return name or "值"


# ---------------------------------------------------------------------------
# 各启发式：返回 (axis_kind, row_label_column, column_label_columns, sub_df, name, description)
# ---------------------------------------------------------------------------

def _split_wide_with_time(df: pd.DataFrame, table_name: str) -> list[tuple]:
    """启发式1：宽表且时间列头为主（指标×年份）。行=指标，列头=时间点。"""
    time_cols = sorted(_time_header_cols(df), key=_natural_key)
    if len(time_cols) < _WIDE_TIME_MIN_TIME_HEADS:
        return []
    total = len(df.columns)
    if total and len(time_cols) / total < _WIDE_TIME_TIME_FRACTION:
        return []
    if len(df) > _WIDE_TIME_HINT_MAX_ROWS:
        return []

    id_cols = [c for c in df.columns if c not in time_cols]
    out: list[tuple] = []
    for _, row in df.iterrows():
        indicator = "; ".join(str(row[c]) for c in id_cols) if id_cols else "指标"
        indicator = _sanitize_series_name(indicator)
        sub_df = pd.DataFrame({
            _TIME_LABEL_COL: [str(c) for c in time_cols],
            _VALUE_LABEL_COL: [row[c] for c in time_cols],
        })
        out.append((
            "time_series", _TIME_LABEL_COL, [_VALUE_LABEL_COL], sub_df,
            indicator, f"{indicator} 随 {_TIME_LABEL_COL} 的变化",
        ))
    return out


def _time_series_frame(
    df: pd.DataFrame, time_col: str, measure_col: str
) -> pd.DataFrame:
    """取「时间 + 指标」两列：按自然时间排序，同一时间点按语义聚合。"""
    sub = df[[time_col, measure_col]].dropna(subset=[time_col]).copy()
    if sub.duplicated(subset=[time_col]).any():
        sub = sub.groupby(
            time_col, as_index=False, dropna=False
        )[measure_col].agg(_measure_agg(measure_col))
    return (
        sub.sort_values(time_col, key=lambda s: s.map(_natural_key))
        .reset_index(drop=True)
    )


def _split_wide_with_metrics(df: pd.DataFrame, column_semantics: dict[str, str]) -> list[tuple]:
    """启发式2：宽表含一时间列 + 多个指标列（时间×指标）。

    多个指标保留在同一条 series 里，规划阶段才能画“多设备/多传感器”折线；
    如果拆成每指标一条 series，用户要求同图比较时 planner 只能选到其中一个。
    每个指标按自身语义聚合（率取均值、计数求和等），并共享同一时间轴。
    """
    time_cols = [c for c, r in column_semantics.items() if r == "time"]
    measure_cols = [c for c, r in column_semantics.items() if r == "measure"]
    if not time_cols or not measure_cols:
        return []

    time_col = time_cols[0]
    sub_df = df[[time_col, *measure_cols]].dropna(subset=[time_col]).copy()
    if sub_df.duplicated(subset=[time_col]).any():
        agg_map = {m: _measure_agg(m) for m in measure_cols}
        sub_df = sub_df.groupby(
            time_col, as_index=False, dropna=False
        )[measure_cols].agg(agg_map)
    sub_df = (
        sub_df.sort_values(time_col, key=lambda s: s.map(_natural_key))
        .reset_index(drop=True)
    )
    shown = "、".join(measure_cols[:3])
    if len(measure_cols) > 3:
        shown += f" 等{len(measure_cols)}项"
    return [(
        "time_series", time_col, list(measure_cols), sub_df,
        _sanitize_series_name(shown),
        f"{shown} 随 {time_col} 的变化",
    )]


def _split_long_or_categorical(df: pd.DataFrame, column_semantics: dict[str, str]) -> list[tuple]:
    """启发式3/4：长表或普通 维度+指标 表。"""
    time_cols = [c for c, r in column_semantics.items() if r == "time"]
    measure_cols = [c for c, r in column_semantics.items() if r == "measure"]
    dim_cols = [c for c, r in column_semantics.items() if r == "dimension"]

    # 3. 长表：一个轴 + 一个值
    if time_cols and measure_cols:
        tc, mc = time_cols[0], measure_cols[0]
        sub = _time_series_frame(df, tc, mc)
        return [(
            "time_series", tc, [mc], sub,
            _sanitize_series_name(mc), f"{mc} 随 {tc} 的变化",
        )]
    # 4. 维度 + 指标
    if dim_cols and measure_cols:
        dc, mcs = dim_cols[0], measure_cols
        try:
            sub = df[[dc, *mcs]].copy()
        except KeyError:
            sub = df[[dc]].copy()
        return [(
            "categorical_comparison", dc, mcs, sub,
            _sanitize_series_name(dc), f"{dc} 维度的指标对比（{', '.join(mcs)}）",
        )]
    return []


def _split_generic(df: pd.DataFrame, table_name: str) -> list[tuple]:
    """启发式5：兜底——整表 generic series（不丢信息）。"""
    return [(
        "generic", None, list(df.columns), df.copy(),
        "全量数据", f"{table_name} 全量数据（{len(df)} 行 × {len(df.columns)} 列）",
    )]


def split_raw_table(
    df: pd.DataFrame,
    table_name: str,
    column_semantics: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """把一张原始表拆成多条系列候选（尚未落盘）。

    Args:
        df: 原始 DataFrame
        table_name: 逻辑表名
        column_semantics: 列语义 (time/measure/dimension/id)；缺省时用 build_profile 推断

    Returns:
        list of dict: {axis_kind, row_label_column, column_label_columns, name, description, df}
        至少返回一条（generic 兜底）。
    """
    if df is None or df.empty:
        df = pd.DataFrame()
    if column_semantics is None:
        column_semantics = _infer_semantics_for_df(df)

    for split in (
        _split_wide_with_time,
        _split_long_with_dimension,
        lambda d, s: _split_wide_with_metrics(d, s),
        lambda d, s: _split_long_or_categorical(d, s),
        lambda d, s: _split_generic(d, table_name),
    ):
        cands = split(df, column_semantics)
        if cands:
            return [
                {
                    "axis_kind": c[0], "row_label_column": c[1],
                    "column_label_columns": c[2], "df": c[3],
                    "name": c[4], "description": c[5],
                }
                for c in cands
            ]
    return _split_generic(df, table_name)


def _approx_unique(series: pd.Series, sample_size: int = 10_000, seed: int = 0) -> int:
    """估算 nunique：大列采样，避免 O(n) 全表扫描。

    小列（≤sample_size）走精确 nunique，大列走 sample + nunique。
    """
    if len(series) <= sample_size:
        return int(series.nunique(dropna=True))
    sample = series.sample(sample_size, random_state=seed)
    nuniq_sample = int(sample.nunique(dropna=True))
    # 用 sample 比例反推全表近似值（线性放大）
    return int(nuniq_sample * len(series) / sample_size)


def _infer_semantics_for_df(df: pd.DataFrame) -> dict[str, str]:
    """直接用 DataFrame 推断列语义（复用 build_profile_from_df 的归一化）。"""
    from service.data_ingestion.profiler import _dtype_to_semtype

    sem_schema = [
        {"name": str(c), "type": _dtype_to_semtype(dtype)}
        for c, dtype in df.dtypes.items()
    ]
    stats = {c: {"approx_unique": _approx_unique(df[c])} for c in df.columns}
    return _infer_column_semantics(sem_schema, stats, len(df))


def build_series_catalog(
    raw_tables: list[RawTable],
    datasets_dir: Path | str,
) -> SeriesCatalog:
    """为一批原始表拆分并落盘 series，写 manifest.json，返回 SeriesCatalog。

    Args:
        raw_tables: list[RawTable]（reader 产出，含 name/df/source_kind/source_path）
        datasets_dir: 会话目录（其中每 series 落一个 .parquet，并写 manifest.json）

    Returns:
        SeriesCatalog
    """
    datasets_dir = Path(datasets_dir)
    datasets_dir.mkdir(parents=True, exist_ok=True)

    all_series: list[SemanticSeries] = []
    used_ids: set[str] = set()

    for rt in raw_tables:
        df: pd.DataFrame = rt.df
        if df is None or df.empty:
            df = pd.DataFrame()
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(x) for x in c) for c in df.columns]

        for spec in split_raw_table(df, rt.name):
            base = _safe_filename(rt.name)
            seg = _safe_filename(spec["name"])
            series_id = f"{base}.{seg}"
            n = 1
            while series_id in used_ids:
                series_id = f"{base}.{seg}_{n}"
                n += 1
            used_ids.add(series_id)

            data_path = datasets_dir / f"{series_id}.parquet"
            sub_df = spec["df"]
            # 存 2-D DataFrame（索引 reset 为真实列，保 read_parquet 无损往返）
            sub_df = sub_df.reset_index(drop=True)
            sub_df.to_parquet(data_path, index=False)
            # 数据形态随 manifest 持久化：规划阶段不用再读 parquet 就能知道
            # 时间点/类别数、指标数、是否含负值，从而按数据选图表类型。
            shape = compute_series_shape(
                sub_df,
                spec["axis_kind"],
                spec["row_label_column"],
                spec["column_label_columns"],
            )

            all_series.append(SemanticSeries(
                series_id=series_id,
                name=_sanitize_series_name(spec["name"]),
                axis_kind=spec["axis_kind"],
                row_label_column=spec["row_label_column"],
                column_label_columns=spec["column_label_columns"],
                data_path=str(data_path.as_posix()),
                source_table=rt.name,
                description=spec["description"],
                # source_kind/source_path 让技能选择能区分图片/PDF/Office 抽表与普通表格，
                # 不在图表代码里硬编码“图片就怎样”，只作为可检索的上下文。
                extra_semantics={
                    "shape": shape,
                    "source_kind": rt.source_kind,
                    "source_path": rt.source_path,
                },
                dtype_info={c: str(t) for c, t in sub_df.dtypes.items()},
            ))

    catalog = SeriesCatalog(datasets_dir=str(datasets_dir.as_posix()), series=all_series)
    write_manifest(catalog, datasets_dir)
    return catalog


def write_manifest(catalog: SeriesCatalog, datasets_dir: Path | str | None = None) -> Path:
    """把 SeriesCatalog 落盘为 manifest.json。

    Args:
        catalog: 待落盘的目录
        datasets_dir: 目标目录；缺省用 catalog.datasets_dir

    Returns:
        manifest.json 的 Path
    """
    datasets_dir = Path(datasets_dir or catalog.datasets_dir)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = datasets_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(catalog.to_json(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path