"""数据源 Reader 模块（v4）。

每个 reader 负责把一种数据源类型读取为 list[RawTable]（pandas DataFrame），
不再注册到 DuckDBManager。
"""

from service.data_ingestion.readers.file_reader import FileReader
from service.data_ingestion.readers.excel_reader import ExcelReader
from service.data_ingestion.readers.database_reader import DatabaseReader
from service.data_ingestion.readers.api_reader import ApiReader
from service.data_ingestion.readers.document_reader import DocumentReader
from service.data_ingestion.readers.archive_reader import ArchiveReader
from service.data_ingestion.readers.llm_tabular_reader import LlmTabularReader

__all__ = [
    "FileReader",
    "ExcelReader",
    "DatabaseReader",
    "ApiReader",
    "DocumentReader",
    "ArchiveReader",
    "LlmTabularReader",
]
