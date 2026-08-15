"""
Pyecharts 纯检索系统
基于 Qwen Embedding 和 LangChain，支持从多级目录加载 Markdown 知识库，
构建向量检索，返回相关文档。
"""

import os
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()
# 配置 HF 镜像加速国内下载（必须在 import huggingface_hub/transformers 之前设置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# LangChain 相关
from langchain_core.embeddings import Embeddings
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_classic.schema import Document

# Sentence Transformers 用于 Qwen3-Embedding
try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False

import torch


# 通用 SentenceTransformer 嵌入（兼容 bge-small-zh / Qwen3-Embedding 等）
class SentenceTransformerEmbeddings(Embeddings):
    """
    基于 SentenceTransformer 的 Embeddings。CPU 友好模型（如 bge-small-zh-v1.5,
    24M 参数）构建/检索都快；也兼容 Qwen3-Embedding（需 GPU）。
    """
    def __init__(self, model_path: str, device: str = None, max_seq_length: int = 512):
        if not HAS_SENTENCE_TRANSFORMERS:
            raise ImportError("请安装 sentence-transformers: pip install sentence-transformers")

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model = SentenceTransformer(model_path, device=device)
        # 限制最大序列长度：pyecharts 示例 avg ~240 token，512 足够且大幅加速 CPU encode
        self.model.max_seq_length = max_seq_length

    def embed_documents(self, texts):
        embeddings = self.model.encode(
            texts, normalize_embeddings=True,
            batch_size=32, show_progress_bar=True,
        )
        return embeddings.tolist()
    
    def embed_query(self, text):
        try:
            embedding = self.model.encode(text, prompt_name="query", normalize_embeddings=True)
        except Exception:
            # 模型不支持 prompt_name（如 bge），用普通 encode
            embedding = self.model.encode(text, normalize_embeddings=True)
        return embedding.tolist()


# ==================== 配置路径（从环境变量读取，带项目根相对默认值）====================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMBEDDING_MODEL_PATH = os.getenv(
    "QWEN_EMBEDDING_PATH",
    str(_PROJECT_ROOT / "RAG" / "models" / "bge-small-zh-v1.5"),  # 本地 CPU 友好模型，避免在线下载超时
)
DATA_ROOT = os.getenv(
    "RAG_DATA_ROOT",
    str(_PROJECT_ROOT / "RAG" / "RAG_Data"),
)
_chroma_env = os.getenv("CHROMA_DB_PATH", "")
CHROMA_PERSIST_DIR = _chroma_env if _chroma_env else str(_PROJECT_ROOT / "runtime" / "chroma")
DEFAULT_K = int(os.getenv("RAG_RETRIEVE_K", "3"))                 # 默认检索返回文档数
# ===================================================================


class RAGRetriever:
    """
    Pyecharts 纯检索器
    提供文档加载、向量库构建、检索功能。
    """

    def __init__(
        self,
        embedding_model_path: str = EMBEDDING_MODEL_PATH,
        data_root: str = DATA_ROOT,
        persist_dir: str = CHROMA_PERSIST_DIR,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        k: int = DEFAULT_K,
    ):
        """
        初始化检索器

        :param embedding_model_path: 本地嵌入模型路径
        :param data_root: 知识库根目录（包含各图表子目录）
        :param persist_dir: Chroma 向量库持久化目录
        :param chunk_size: 文本切分块大小
        :param chunk_overlap: 块重叠大小
        :param k: 检索返回的最相关文档块数量
        """
        self.embedding_model_path = embedding_model_path
        self.data_root = data_root
        self.persist_dir = persist_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.k = k

        # 初始化嵌入模型
        self.embeddings = self._init_embeddings()

        # 初始化向量库（加载或构建）
        self.vectorstore = self._build_or_load_vectorstore()

        # 检索器
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": self.k}
        )

    def _init_embeddings(self):
        """初始化嵌入模型：本地路径优先，否则用在线 HF 模型（自动下载）"""
        if os.path.exists(self.embedding_model_path):
            print(f"使用本地嵌入模型: {self.embedding_model_path}")
        else:
            print(f"使用在线嵌入模型: {self.embedding_model_path}（首次需下载，已配 hf-mirror 镜像）")
        return SentenceTransformerEmbeddings(model_path=self.embedding_model_path)

    def _load_documents(self):
        """
        递归加载 DATA_ROOT 下所有 .md 文件
        """
        if not os.path.exists(self.data_root):
            raise FileNotFoundError(f"知识库路径不存在: {self.data_root}")

        loader = DirectoryLoader(
            self.data_root,
            glob="**/*.md",
            loader_cls=TextLoader,
            show_progress=True,
            recursive=True,
            loader_kwargs={"encoding": "utf-8"}
        )
        docs = loader.load()
        print(f"成功加载 {len(docs)} 个文档")

        return docs

    def _split_documents(self, docs):
        """将文档切分成更小的块。

        RAG 知识库主要是 pyecharts 示例（markdown 中嵌 python 代码围栏），
        分隔符优先级按语义强度排列：
        1. 三个反引号（```）：保证代码围栏首尾不被切开
        2. markdown 标题 (## / ### / ####)：按小节切
        3. 空行 / 换行：段落级
        4. 中文标点与空格：细粒度回退
        """
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=[
                "\n```",
                "\n## ",
                "\n### ",
                "\n#### ",
                "\n\n",
                "\n",
                "。",
                "；",
                " ",
                ""
            ]
        )
        chunks = text_splitter.split_documents(docs)
        print(f"切分后得到 {len(chunks)} 个文本块")
        return chunks

    def _build_or_load_vectorstore(self):
        """
        如果持久化目录已存在且非空，则加载已有向量库；
        否则加载文档、切分、构建向量库并持久化。
        """
        if os.path.exists(self.persist_dir) and os.listdir(self.persist_dir):
            print(f"加载已有向量库: {self.persist_dir}")
            vectorstore = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings
            )
            # 检测空库：count()==0 说明是上次构建失败的残留空壳，需重建
            try:
                doc_count = vectorstore._collection.count()
            except Exception:
                doc_count = 0
            if doc_count > 0:
                print(f"已有 {doc_count} 条向量，直接复用")
                return vectorstore
            print(f"⚠️ 检测到空库（0 文档），可能是上次构建失败残留，将重新构建...")

        print("开始加载原始文档...")
        docs = self._load_documents()
        if not docs:
            raise RuntimeError("未加载到任何文档，请检查知识库目录")

        print("开始切分文档...")
        chunks = self._split_documents(docs)

        print("开始构建向量库并持久化...")
        vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=self.persist_dir
        )
        print(f"向量库已持久化到: {self.persist_dir}")

        return vectorstore

    def retrieve(self, query: str):
        """
        检索相关文档

        :param query: 查询文本
        :return: 相关文档列表
        """
        return self.retriever.invoke(query)

    def get_retriever(self):
        """返回检索器，便于自定义使用"""
        return self.retriever


# ==================== 使用示例 ====================
if __name__ == "__main__":
    retriever = RAGRetriever()
    print("\n检索器初始化完成！")
    print("使用方法：docs = retriever.retrieve('你的查询')")
