"""数据源 Reader 模块。

每个 reader 负责将一种数据源类型注册到 DuckDBManager 中。
"""

from service.data_ingestion.readers.file_reader import FileReader
from service.data_ingestion.readers.excel_reader import ExcelReader
from service.data_ingestion.readers.database_reader import DatabaseReader
from service.data_ingestion.readers.api_reader import ApiReader
from service.data_ingestion.readers.document_reader import DocumentReader
from service.data_ingestion.readers.archive_reader import ArchiveReader

__all__ = [
    "FileReader",
    "ExcelReader",
    "DatabaseReader",
    "ApiReader",
    "DocumentReader",
    "ArchiveReader",
]
