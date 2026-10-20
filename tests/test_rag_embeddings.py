"""RAG 嵌入封装的离线回归：排序分批后必须按原顺序返回向量。"""
import numpy as np

from RAG.RAG_main import SentenceTransformerEmbeddings


class _FakeModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), kwargs))
        return np.array([[float(len(t))] for t in texts])


def test_embed_documents_sorts_by_length_but_keeps_order():
    wrapper = SentenceTransformerEmbeddings.__new__(SentenceTransformerEmbeddings)
    wrapper.model = _FakeModel()
    wrapper.batch_size = 8

    result = wrapper.embed_documents(["bbb", "a", "cc"])

    # 送进模型的顺序按长度升序，减少 padding
    assert wrapper.model.calls[0][0] == ["a", "cc", "bbb"]
    # 返回顺序与输入一致
    assert result == [[3.0], [1.0], [2.0]]
    assert wrapper.model.calls[0][1]["normalize_embeddings"] is True


def test_embed_documents_empty_input():
    wrapper = SentenceTransformerEmbeddings.__new__(SentenceTransformerEmbeddings)
    wrapper.model = _FakeModel()
    wrapper.batch_size = 8

    assert wrapper.embed_documents([]) == []


def test_env_path_treats_empty_as_unset(monkeypatch):
    """`.env` 模板里的 RAG_DATA_ROOT="" 必须回退默认值，不能变成空路径。"""
    from RAG.RAG_main import _env_path

    monkeypatch.setenv("RAG_DATA_ROOT", "")
    assert _env_path("RAG_DATA_ROOT", "fallback") == "fallback"

    monkeypatch.setenv("RAG_DATA_ROOT", "D:/data")
    assert _env_path("RAG_DATA_ROOT", "fallback") == "D:/data"


def test_default_retriever_is_cached(monkeypatch):
    """0.6B 模型不能每个图表任务都重新加载。"""
    import RAG.RAG_main as module

    created = []

    class _FakeRetriever:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr(module, "RAGRetriever", _FakeRetriever)
    monkeypatch.setattr(module, "_default_retriever", None)

    first = module.get_default_retriever()
    second = module.get_default_retriever()

    assert first is second
    assert len(created) == 1
