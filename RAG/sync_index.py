"""RAG 知识库增量同步。

CPU 上从零重建整个向量库约 30-40 分钟；只新增/改动少量 Markdown 时，
用本脚本按 source 增量 upsert 即可，无需删除 ``runtime/chroma``。

用法（项目根目录，用 venv 里的解释器）::

    .venv\\Scripts\\python.exe -m RAG.sync_index RAG/RAG_Data/Scatter/scatter_base.md
    .venv\\Scripts\\python.exe -m RAG.sync_index --missing
    .venv\\Scripts\\python.exe -m RAG.sync_index --all --prune

- 显式给文件 / 目录：同步这些 Markdown（已存在则先删旧 chunk 再写入）
- ``--missing``：只补充向量库里还没有的 Markdown（默认行为）
- ``--all``：同步 ``RAG_Data`` 下全部 Markdown
- ``--prune``：删除源文件已不存在的向量条目

换 embedding 模型后仍要删/改名 ``runtime/chroma`` 全量重建，本脚本不处理维度变更。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from RAG.RAG_main import DATA_ROOT, RAGRetriever


def _iter_markdown(paths: list[str]) -> list[Path]:
    """把文件/目录参数展开为 Markdown 文件列表（去重、排序）。"""
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(x for x in sorted(p.rglob("*.md")) if x.is_file())
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(f"路径不存在: {p}")
    # 去重（保留首次出现顺序）
    seen: set[str] = set()
    unique: list[Path] = []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _store_sources(retriever: RAGRetriever) -> dict[str, list[str]]:
    """返回向量库里 source 路径 -> chunk id 列表。"""
    got = retriever.vectorstore.get(include=["metadatas"])
    mapping: dict[str, list[str]] = {}
    for doc_id, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
        src = str((meta or {}).get("source") or "")
        if src:
            mapping.setdefault(src, []).append(doc_id)
    return mapping


def sync(
    retriever: RAGRetriever,
    targets: list[Path],
    prune: bool = False,
) -> dict:
    """把 ``targets`` 增量写入向量库；``prune`` 时清理源文件已删除的条目。"""
    existing = _store_sources(retriever)
    stats = {"added": 0, "files": 0, "pruned": 0}

    for path in targets:
        result = retriever.sync_markdown(path)
        stats["added"] += result["added"]
        stats["files"] += 1
        if result["replaced"]:
            print(f"更新 {path}（替换 {result['replaced']} 条，新增 {result['added']} 条）")
        else:
            print(f"新增 {path}（{result['added']} 条）")

    if prune:
        for src, ids in existing.items():
            if not Path(src).exists():
                retriever.vectorstore.delete(ids=ids)
                stats["pruned"] += len(ids)
                print(f"清理失效来源 {src}（{len(ids)} 条）")

    try:
        stats["total"] = retriever.vectorstore._collection.count()
    except Exception:
        stats["total"] = -1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG 知识库增量同步")
    parser.add_argument("paths", nargs="*", help="要同步的 Markdown 文件或目录")
    parser.add_argument("--all", action="store_true", help="同步 RAG_Data 下全部 Markdown")
    parser.add_argument("--missing", action="store_true", help="只补充还没有的 Markdown（默认）")
    parser.add_argument("--prune", action="store_true", help="删除源文件已不存在的向量条目")
    args = parser.parse_args(argv)

    retriever = RAGRetriever()
    existing = _store_sources(retriever)

    if args.paths:
        targets = _iter_markdown(args.paths)
    else:
        all_files = [p for p in sorted(Path(DATA_ROOT).rglob("*.md")) if p.is_file()]
        if args.all:
            targets = all_files
        else:
            targets = [p for p in all_files if str(p.resolve()) not in existing]

    if not targets and not args.prune:
        print("没有需要同步的文件（向量库已是最新）")
        return 0

    stats = sync(retriever, targets, prune=args.prune)
    print(
        f"完成：文件 {stats['files']} 个，新增 chunk {stats['added']} 条，"
        f"清理 {stats['pruned']} 条，当前共 {stats['total']} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
