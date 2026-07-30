import re
import os
from functools import lru_cache
from pathlib import Path

try:
    import pathspec
except ImportError:
    pathspec = None


MAX_INCLUDE_DEPTH = 5
MAX_MEMORY_CHARACTER_COUNT = 40000

_REPO_ROOT = Path(__file__).resolve().parents[2]

_INCLUDE_PATTERN = re.compile(r'@([\w./\-]+\.md)')
_BLOCK_HTML_COMMENT_PATTERN = re.compile(r'<!--.*?-->', re.DOTALL)
_FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


def _parse_frontmatter_paths(content):
    match = _FRONTMATTER_PATTERN.match(content)
    if not match:
        return None, content
    fm_text = match.group(1)
    body = content[match.end():]
    paths = []
    for line in fm_text.splitlines():
        line = line.strip()
        if line.lower().startswith('paths:'):
            value = line.split(':', 1)[1].strip()
            if value.startswith('[') and value.endswith(']'):
                inner = value[1:-1]
                for item in re.split(r'[,\s]+', inner.strip()):
                    item = item.strip().strip('"').strip("'")
                    if item:
                        paths.append(item)
            elif value:
                paths.append(value.strip('"').strip("'"))
            break
    if not paths:
        return None, content
    return paths, body


def _matches_paths(file_paths, patterns):
    if not patterns:
        return True
    if pathspec is None:
        return True
    spec = pathspec.PathSpec.from_lines('gitwildmatch', patterns)
    for fp in file_paths:
        try:
            rel = str(Path(fp).resolve().relative_to(_REPO_ROOT)).replace('\\', '/')
        except (ValueError, TypeError):
            rel = str(fp).replace('\\', '/')
        if spec.match_file(rel):
            return True
    return False


def _strip_block_html_comments(content):
    return _BLOCK_HTML_COMMENT_PATTERN.sub('', content)


def _resolve_include_path(ref, current_file_dir):
    p = Path(ref)
    if not p.is_absolute():
        candidates = [
            (current_file_dir / p).resolve(),
            (_REPO_ROOT / p).resolve(),
        ]
    else:
        candidates = [p.resolve()]
    p = None
    for c in candidates:
        if c.exists() and c.is_file():
            p = c
            break
    if p is None:
        return None
    if p.suffix.lower() != '.md':
        return None
    if not p.exists() or not p.is_file():
        return None
    if _REPO_ROOT not in p.resolve().parents and p.resolve() != _REPO_ROOT:
        return None
    return p


def _load_file_with_includes(file_path, depth, visited, active_file_paths):
    file_path = file_path.resolve()
    if file_path in visited or depth > MAX_INCLUDE_DEPTH:
        return ''
    visited.add(file_path)

    try:
        raw = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''

    paths, body = _parse_frontmatter_paths(raw)
    if paths is not None and active_file_paths is not None:
        if not _matches_paths(active_file_paths, paths):
            return ''

    body = _strip_block_html_comments(body)

    def _replacer(m):
        ref = m.group(1)
        resolved = _resolve_include_path(ref, file_path.parent)
        if resolved is None:
            return m.group(0)
        included = _load_file_with_includes(resolved, depth + 1, visited, active_file_paths)
        return included

    expanded = _INCLUDE_PATTERN.sub(_replacer, body)
    return expanded


def _memory_files():
    candidates = []
    candidates.append(_REPO_ROOT / '.claude' / 'AGENTS.md')
    candidates.append(_REPO_ROOT / 'AGENTS.md')
    rules_dir = _REPO_ROOT / '.claude' / 'rules'
    if rules_dir.is_dir():
        candidates.extend(sorted(rules_dir.glob('*.md')))
    candidates.append(_REPO_ROOT / 'AGENTS.local.md')
    return [c for c in candidates if c.is_file()]


def _build_project_memory(active_file_paths=None):
    parts = []
    visited = set()
    for f in _memory_files():
        content = _load_file_with_includes(f, 0, visited, active_file_paths)
        if content.strip():
            parts.append(content.strip())
    merged = '\n\n'.join(parts)
    if len(merged) > MAX_MEMORY_CHARACTER_COUNT:
        merged = merged[:MAX_MEMORY_CHARACTER_COUNT] + '\n<!-- memory truncated -->'
    return merged


@lru_cache(maxsize=1)
def get_project_memory():
    return _build_project_memory(None)


def reset_project_memory_cache(reason=''):
    get_project_memory.cache_clear()


def get_project_memory_for_files(file_paths):
    return _build_project_memory(tuple(file_paths) if file_paths else None)
