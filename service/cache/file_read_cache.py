import threading
from collections import OrderedDict
from pathlib import Path

try:
    from service.constants import CSV_ENCODINGS as _DEFAULT_ENCODINGS
except ImportError:
    from ..constants import CSV_ENCODINGS as _DEFAULT_ENCODINGS


class FileReadCache:
    """带 mtime 校验的 FIFO 文件读取缓存。"""

    def __init__(self, max_size=100):
        self.max_size = max_size
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def _get_mtime(self, path):
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def _detect_encoding_and_read(self, path):
        for enc in _DEFAULT_ENCODINGS:
            try:
                with open(path, 'r', encoding=enc) as f:
                    content = f.read()
                return content.replace('\r\n', '\n'), enc
            except UnicodeDecodeError:
                continue
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return content.replace('\r\n', '\n'), 'utf-8-ignore'

    def read_file(self, path, encoding=None):
        """读取文件，命中缓存且 mtime 未变则返回缓存，否则重读。"""
        path = str(Path(path).resolve())
        mtime = self._get_mtime(path)
        if mtime is None:
            return None, None

        with self._lock:
            entry = self._cache.get(path)
            if entry is not None and entry[1] == mtime:
                self._cache.move_to_end(path)
                return entry[0], entry[2]

        if encoding is not None:
            try:
                with open(path, 'r', encoding=encoding) as f:
                    content = f.read().replace('\r\n', '\n')
                used_enc = encoding
            except UnicodeDecodeError:
                content, used_enc = self._detect_encoding_and_read(path)
        else:
            content, used_enc = self._detect_encoding_and_read(path)

        with self._lock:
            self._cache[path] = (content, mtime, used_enc)
            self._cache.move_to_end(path)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

        return content, used_enc

    def get_cached(self, path):
        """仅查询缓存，不触发读取。返回 (content, mtime, encoding) 或 None。"""
        path = str(Path(path).resolve())
        with self._lock:
            return self._cache.get(path)

    def invalidate(self, path):
        """显式失效单个路径。"""
        path = str(Path(path).resolve())
        with self._lock:
            self._cache.pop(path, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __len__(self):
        with self._lock:
            return len(self._cache)

    def get_or_compute(self, path, compute_func, *args, **kwargs):
        """通用缓存：按 (path, mtime) 缓存 compute_func 的结果。

        用于 pandas 读取结果等需要后处理的缓存。
        """
        path = str(Path(path).resolve())
        mtime = self._get_mtime(path)
        if mtime is None:
            return compute_func(path, *args, **kwargs)

        cache_key = ('__computed__', path)
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None and entry[1] == mtime:
                self._cache.move_to_end(cache_key)
                return entry[0]

        result = compute_func(path, *args, **kwargs)

        with self._lock:
            self._cache[cache_key] = (result, mtime, 'computed')
            self._cache.move_to_end(cache_key)
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

        return result


_file_cache = FileReadCache(max_size=100)


def get_file_cache():
    return _file_cache


def read_file(path, encoding=None):
    return _file_cache.read_file(path, encoding=encoding)
