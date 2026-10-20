"""RAG 增量同步工具回归（不加载真实 embedding 模型）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from RAG.sync_index import _iter_markdown, _store_sources, sync


def test_iter_markdown_expands_dirs_and_dedups(tmp_path: Path):
    (tmp_path / "a.md").write_text("# a", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("# b", encoding="utf-8")
    (sub / "note.txt").write_text("ignore", encoding="utf-8")

    # 目录 + 重复文件：去重后只剩 a.md / b.md
    files = _iter_markdown([str(tmp_path), str(tmp_path / "a.md")])
    names = sorted(p.name for p in files)
    assert names == ["a.md", "b.md"]


def test_iter_markdown_missing_path_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        _iter_markdown([str(tmp_path / "nope.md")])


class _FakeCollection:
    def count(self) -> int:
        return 3


class _FakeVectorStore:
    def __init__(self, entries: list[tuple[str, dict]]):
        self.entries = entries
        self.deleted: list[str] = []
        self.added: list = []

    def get(self, include=None):
        return {
            "ids": [doc_id for doc_id, _ in self.entries],
            "metadatas": [meta for _, meta in self.entries],
        }

    def delete(self, ids):
        self.deleted.extend(ids)

    def add_documents(self, chunks):
        self.added.extend(chunks)

    @property
    def _collection(self):
        return _FakeCollection()


class _FakeRetriever:
    def __init__(self, store: _FakeVectorStore):
        self.vectorstore = store
        self.synced: list[str] = []

    def sync_markdown(self, path):
        self.synced.append(str(path))
        return {"path": str(path), "added": 2, "replaced": 0}


def test_store_sources_groups_ids_by_source():
    store = _FakeVectorStore(
        [("id1", {"source": "x.md"}), ("id2", {"source": "x.md"}), ("id3", {"source": "y.md"})]
    )

    assert _store_sources(_FakeRetriever(store)) == {"x.md": ["id1", "id2"], "y.md": ["id3"]}


def test_sync_prunes_sources_that_no_longer_exist(tmp_path: Path):
    alive = tmp_path / "alive.md"
    alive.write_text("# alive", encoding="utf-8")
    stored = str(tmp_path / "removed.md")  # 文件故意不存在
    store = _FakeVectorStore([("old1", {"source": stored}), ("keep", {"source": str(alive)})])
    retriever = _FakeRetriever(store)

    stats = sync(retriever, [alive], prune=True)

    assert retriever.synced == [str(alive)]
    assert stats["files"] == 1
    assert stats["added"] == 2
    assert store.deleted == ["old1"]
    assert stats["pruned"] == 1
    assert stats["total"] == 3
