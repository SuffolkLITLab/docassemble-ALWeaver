# do not pre-load

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

from .analysis_cache import FileResultCache


def test_file_edits_deletions_and_mutated_results(tmp_path):
    source = tmp_path / "include.yml"
    source.write_text("old")
    cache = FileResultCache()

    def compute(dependencies):
        dependencies.add(str(source))
        return {"text": source.read_text() if source.exists() else "missing"}

    loader = Mock(side_effect=compute)
    cache.get((7, "project"), loader)["text"] = "corrupted"
    assert cache.get((7, "project"), loader)["text"] == "old"
    assert loader.call_count == 1
    source.write_text("new")
    assert cache.get((7, "project"), loader)["text"] == "new"
    source.unlink()
    assert cache.get((7, "project"), loader)["text"] == "missing"
    assert loader.call_count == 3


def test_same_key_requests_coalesce_and_cache_is_bounded(tmp_path):
    source = tmp_path / "main.yml"
    source.touch()
    cache = FileResultCache(max_bytes=64)

    def compute(dependencies):
        dependencies.add(str(source))
        return {"data": "x" * 20}

    loader = Mock(side_effect=compute)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(list(pool.map(lambda _: cache.get("same", loader), range(20)))) == 20
    assert loader.call_count == 1
    for index in range(100):
        cache.get(index, loader)
    assert cache._bytes <= 64
    cache.get("same", loader)
    assert loader.call_count == 102  # Evicted, not retained without a bound.


def test_file_changed_during_analysis_is_not_cached(tmp_path):
    source = tmp_path / "main.yml"
    source.write_text("before")
    cache = FileResultCache()

    def compute(dependencies):
        dependencies.add(str(source))
        source.write_text("after")
        return {"text": "before"}

    cache.get("key", compute)
    assert not cache._entries


def test_symbol_cache_tracks_transitive_and_empty_includes(tmp_path, monkeypatch):
    from docassemble.base.parse import Interview
    from .editor_utils import _playground_symbols_without_execution

    main = tmp_path / "main.yml"
    child = tmp_path / "child.yml"
    leaf = tmp_path / "leaf.yml"
    main.write_text("include:\n  - child.yml\n")
    child.write_text("include:\n  - leaf.yml\n")
    leaf.write_text("# Initially empty\n")
    pg = SimpleNamespace(get_file=lambda filename: str(main))
    reads = []
    import docassemble.base.parse as parse

    monkeypatch.setattr(parse, "get_main_page_parts", lambda: {})
    original = Interview.read_from

    def read(self, source):
        reads.append(source.path)
        return original(self, source)

    monkeypatch.setattr(Interview, "read_from", read)
    _playground_symbols_without_execution(pg, 7, "default", "main.yml")
    initial_reads = len(reads)
    assert initial_reads == 3
    _playground_symbols_without_execution(pg, 7, "default", "main.yml")
    assert len(reads) == initial_reads
    leaf.write_text("question: Name\nfields:\n  - Name: included_name\n")
    variables, _, _ = _playground_symbols_without_execution(
        pg, 7, "default", "main.yml"
    )
    assert "included_name" in variables["fields_used"]
    assert len(reads) == 2 * initial_reads
    # Owner and project identities must not reuse another owner's parse.
    _playground_symbols_without_execution(pg, 8, "default", "main.yml")
    assert len(reads) == 3 * initial_reads
