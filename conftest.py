# do not pre load

import importlib.util
import mimetypes
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator

import pytest


def _local_file_finder(file_reference: Any, **kwargs: Any) -> Dict[str, Any]:
    """Resolve package files used by tests without Docassemble's server hooks."""
    if not isinstance(file_reference, str):
        return {"fullpath": None, "mimetype": None}
    if ":" in file_reference:
        package_name, relative_name = file_reference.split(":", 1)
    else:
        package_name, relative_name = "docassemble.ALWeaver", file_reference
    if package_name == "ALWeaver":
        package_name = "docassemble.ALWeaver"
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        return {"fullpath": None, "mimetype": None}
    package_paths = spec.submodule_search_locations
    if not package_paths:
        return {"fullpath": None, "mimetype": None}
    path = Path(next(iter(package_paths))) / relative_name
    mimetype, _encoding = mimetypes.guess_type(path.name)
    return {
        "fullpath": str(path) if path.exists() else None,
        "mimetype": mimetype,
        "filename": path.name,
    }


@pytest.fixture(autouse=True)
def docassemble_test_context(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide the minimal server and thread context Docassemble tests expect."""
    try:
        import defusedxml.ElementTree  # type: ignore # Prevent NLTK inisec guard from blocking CWD-nested venv
    except ImportError:
        pass
    import docassemble.base.dates as da_dates
    import docassemble.base.functions as da_functions
    import docassemble.base.util as da_util

    monkeypatch.setattr(da_functions, "get_configuration", lambda: {})
    monkeypatch.setattr(da_dates, "get_configuration", lambda: {})
    monkeypatch.setattr(da_dates, "get_default_timezone", lambda: "UTC")
    monkeypatch.setattr(da_util, "file_finder", _local_file_finder)
    try:
        from docassemble.base.thread_context import empty_globals, global_context
    except ImportError:
        yield
        return

    globals_for_test = empty_globals()
    globals_for_test.current_question = SimpleNamespace(package="ALWeaver")
    with global_context(globals_for_test):
        yield
