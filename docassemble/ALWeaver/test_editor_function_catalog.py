# do not pre-load
"""Function discovery must reflect imports without executing author code."""

from types import ModuleType, SimpleNamespace

from .editor_function_catalog import interview_function_catalog, local_function_catalog


def test_transitive_imports_relative_names_exports_and_help():
    def calculate(amount: float, digits=2, *, symbol=True):
        """Format a monetary amount."""
        raise AssertionError("Discovery must not call a function")

    module = ModuleType("docassemble.AssemblyLine.al_general")
    module.calculate = calculate
    module.hidden = calculate
    module.__all__ = ["calculate"]
    toolbox = ModuleType("docassemble.ALToolbox.misc")
    toolbox.utility = calculate
    unrelated = ModuleType("unrelated")
    unrelated.never_offer = calculate
    questions = [
        SimpleNamespace(
            question_type="modules",
            package="docassemble.AssemblyLine",
            module_list=[".al_general"],
        ),
        SimpleNamespace(
            question_type="imports",
            package="docassemble.ALToolbox",
            module_list=[".misc"],
        ),
    ]
    catalog = interview_function_catalog(
        SimpleNamespace(questions_list=questions),
        {module.__name__: module, toolbox.__name__: toolbox, "unrelated": unrelated},
    )
    assert "calculate" in catalog
    assert "docassemble.ALToolbox.misc.utility" in catalog
    assert "utility" not in catalog
    assert "hidden" not in catalog
    assert "never_offer" not in catalog
    assert catalog["calculate"]["doc"] == "Format a monetary amount."
    assert "digits=2" in catalog["calculate"]["signature"]
    assert catalog["calculate"]["parameters"][-1] == {
        "name": "symbol",
        "kind": "KEYWORD_ONLY",
        "required": False,
    }


def test_local_functions_have_complete_static_signatures():
    catalog = local_function_catalog('''
def total(amount: float, /, digits=2, *extras, symbol=True, **options):
    """Add an amount without executing this body."""
    raise RuntimeError("not executed")
''')
    info = catalog["total"]
    assert (
        info["signature"]
        == "total(amount: float, /, digits=2, *extras, symbol=True, **options)"
    )
    assert [parameter["kind"] for parameter in info["parameters"]] == [
        "POSITIONAL_ONLY",
        "POSITIONAL_OR_KEYWORD",
        "VAR_POSITIONAL",
        "KEYWORD_ONLY",
        "VAR_KEYWORD",
    ]
    assert info["parameters"][0]["required"]
    assert not info["parameters"][1]["required"]
    assert local_function_catalog("def invalid(") == {}


def test_unloaded_declared_module_is_read_without_importing_or_calling(
    tmp_path, monkeypatch
):
    source = tmp_path / "matrix_unloaded_helpers.py"
    source.write_text('''
raise AssertionError("Module must not be imported during discovery")
__all__ = ["public_helper"]
def public_helper(value=2):
    """Static help."""
    raise AssertionError("Function must not be called")
def hidden_helper():
    pass
''')
    monkeypatch.syspath_prepend(str(tmp_path))
    interview = SimpleNamespace(
        questions_list=[
            SimpleNamespace(
                question_type="modules",
                module_list=["matrix_unloaded_helpers"],
                package="example",
            )
        ]
    )
    catalog = interview_function_catalog(interview, {})
    assert catalog["public_helper"]["signature"] == "public_helper(value=2)"
    assert catalog["public_helper"]["origin"] == "matrix_unloaded_helpers"
    assert "hidden_helper" not in catalog


def test_playground_discovery_parses_selected_project_without_assembly(
    tmp_path, monkeypatch
):
    import sys
    from .editor_utils import _playground_symbols_without_execution

    source_file = tmp_path / "questions.yml"
    source_file.write_text("question: Example\n")
    captured = {}

    def source(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            **kwargs, set_content=lambda content: captured.update(content=content)
        )

    def interview(**kwargs):
        return SimpleNamespace(
            names_used={"root_value"},
            questions={"included_value": []},
            questions_list=[
                SimpleNamespace(
                    question_type="code",
                    sourcecode="def local_helper():\n    raise RuntimeError()",
                    names_used=set(),
                    mako_names=set(),
                    fields_used={"included_value"},
                    from_source=SimpleNamespace(
                        path="docassemble.playground7MyProject:included.yml"
                    ),
                )
            ],
        )

    monkeypatch.setitem(
        sys.modules, "docassemble.base.parse", SimpleNamespace(Interview=interview)
    )
    monkeypatch.setitem(
        sys.modules,
        "docassemble.base.interview_source",
        SimpleNamespace(InterviewSourceFile=source),
    )
    pg = SimpleNamespace(get_file=lambda filename: str(source_file))
    variables, functions, origins = _playground_symbols_without_execution(
        pg, 7, "MyProject", "questions.yml"
    )
    assert captured["package"] == "docassemble.playground7MyProject"
    assert captured["filepath"] == str(source_file)
    assert captured["content"] == "question: Example\n"
    assert captured["path"].endswith("MyProject:questions.yml")
    assert variables["all_names_reduced"] == {"root_value", "included_value"}
    assert "local_helper" in functions
    assert origins["included_value"] == [
        "docassemble.playground7MyProject:included.yml"
    ]


def test_included_code_and_suppressed_util():
    util = ModuleType("docassemble.base.util")
    util.never_offer = lambda: None
    interview = SimpleNamespace(
        consolidated_metadata={"suppress loading util": True},
        questions_list=[
            SimpleNamespace(
                question_type="code",
                sourcecode='def included(value):\n    """Included helper."""\n    return value',
            )
        ],
    )
    catalog = interview_function_catalog(interview, {util.__name__: util})
    assert "never_offer" not in catalog
    assert catalog["included"]["signature"] == "included(value)"
    assert catalog["included"]["doc"] == "Included helper."
    assert "len" in catalog


def test_unprintable_default_does_not_break_discovery():
    class Unprintable:
        def __repr__(self):
            raise RuntimeError("default is not available")

    def helper(value=Unprintable()):
        """Still useful help."""

    module = ModuleType("helpers")
    module.helper = helper
    interview = SimpleNamespace(
        questions_list=[
            SimpleNamespace(
                question_type="modules",
                module_list=["helpers"],
                package="example",
            )
        ]
    )
    catalog = interview_function_catalog(interview, {"helpers": module})
    assert catalog["helper"]["signature"] == "helper(…)"
    assert catalog["helper"]["doc"] == "Still useful help."


def test_declaring_util_explicitly_still_offers_only_the_curated_names():
    util = ModuleType("docassemble.base.util")
    util.defined = lambda variable_name: None
    util.bulky_helper = lambda: None
    legal = ModuleType("docassemble.base.legal")
    legal.bulky_helper = lambda: None
    interview = SimpleNamespace(
        consolidated_metadata={},
        questions_list=[
            SimpleNamespace(
                question_type="modules",
                package="docassemble.ALWeaver",
                module_list=["docassemble.base.util", "docassemble.base.legal"],
            )
        ],
    )
    catalog = interview_function_catalog(
        interview, {util.__name__: util, legal.__name__: legal}
    )
    assert "defined" in catalog
    assert "bulky_helper" not in catalog


def test_a_qualified_import_of_util_still_spells_out_its_names():
    util = ModuleType("docassemble.base.util")
    util.bulky_helper = lambda: None
    interview = SimpleNamespace(
        consolidated_metadata={},
        questions_list=[
            SimpleNamespace(
                question_type="imports",
                package="docassemble.ALWeaver",
                module_list=["docassemble.base.util"],
            )
        ],
    )
    catalog = interview_function_catalog(interview, {util.__name__: util})
    assert "docassemble.base.util.bulky_helper" in catalog
