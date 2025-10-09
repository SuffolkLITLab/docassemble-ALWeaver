from typing import Any, Dict, List, Optional, Union

import ruamel.yaml as yaml
from docassemble.base.util import log, DADict, DAList, DAStore, path_and_mimetype
from packaging.version import Version
from more_itertools import unique_everseen


__all__ = [
    "get_possible_deps_as_choices",
    "get_pypi_deps_from_choices",
    "get_yml_deps_from_choices",
    "SettingsList",
    "load_capabilities",
    "advertise_capabilities",
    "_package_name",
    "get_full_dep_details",
    "get_matching_deps",
    "get_output_mako_choices",
    "get_output_mako_package_and_path",
]


_CAPABILITY_LOAD_DEFAULTS: Dict[str, Any] = {
    "base": "docassemble.ALWeaver",
    "minimum_version": "1.5",
    "include_playground": False,
}


_capability_cache: Optional[Dict[str, Any]] = None


def _package_name(package_name: Optional[str] = None):
    """Get package name without the name of the current module, like: docassemble.ALWeaver instead of
    docassemble.ALWeaver.advertise_capabilities"""
    if not package_name:
        package_name = __name__
    try:
        return ".".join(package_name.split(".")[:-1])
    except:
        return package_name


class SettingsList(DAList):
    """
    A simple list that can sync itself to a DAStore.
    """

    def init(self, *pargs, **kwargs):
        super().init(*pargs, **kwargs)

    def hook_after_gather(self):
        if hasattr(self, "store"):
            self.store.set(self.instanceName, self)

    def __str__(self):
        return "\n".join(self.complete_elements())


def load_capabilities(
    base: str = "docassemble.ALWeaver",
    minimum_version: str = "1.5",
    include_playground: bool = False,
) -> Dict[str, Any]:
    """
    Load and return a dictionary containing all advertised capabilities matching
    the specified minimum version, and optionally include capabilities that were
    advertised from a namespace matching docassemble.playground*. The local
    capabilities will always be the default configuration.
    """
    current_package_name = _package_name()

    this_yaml = path_and_mimetype(
        f"{current_package_name}:data/sources/configuration_capabilities.yml"
    )[0]
    weaverdata = DAStore("weaverdata", base=base)
    published_configuration_capabilities = (
        weaverdata.get("published_configuration_capabilities") or {}
    )
    try:
        yaml_loader = yaml.YAML(typ="safe", pure=True)
        with open(this_yaml) as f:
            first_file = yaml_loader.load(f)

        capabilities = {"Default configuration": first_file}
    except:
        capabilities = {}

    for key in list(published_configuration_capabilities.keys()):
        # Filter configurations based on minimum published version
        if isinstance(published_configuration_capabilities[key], tuple) and Version(
            published_configuration_capabilities[key][1]
        ) < Version(minimum_version):
            log(
                "Skipping published weaver configuration {key}:{published_configuration_capabilities[key]} because it is below the minimum version {minimum_version}. Consider updating the {key} package."
            )
            del published_configuration_capabilities[key]
        # Filter out capability files unless the package is installed system-wide
        if not include_playground and key.startswith("docassemble.playground"):
            del published_configuration_capabilities[key]

    for package_name in published_configuration_capabilities:
        # Don't add the current package twice
        if not current_package_name == package_name:
            path = path_and_mimetype(
                f"{package_name}:data/sources/{published_configuration_capabilities[package_name][0]}"
            )[0]
            try:
                yaml_loader = yaml.YAML(typ="safe", pure=True)
                with open(path) as f:
                    capabilities[package_name] = yaml_loader.load(f)
            except:
                log(f"Unable to load published Weaver configuration file {path}")

    return capabilities


def _get_capabilities(refresh: bool = False) -> Dict[str, Any]:
    """Return cached capabilities, optionally refreshing from the datastore."""

    global _capability_cache
    if refresh or _capability_cache is None:
        _capability_cache = load_capabilities(**_CAPABILITY_LOAD_DEFAULTS)
    return _capability_cache


def get_possible_deps_as_choices(dep_category=None):
    """Gets the possible yml files that the generated interview will depend on"""

    dep_choices = []

    capabilities = _get_capabilities()

    # TODO: do we want to prefix the choice with the package name?
    for capability in capabilities:
        if dep_category == "organization":
            dep_choices.extend(
                [
                    {item.get("include_name"): item.get("description")}
                    for item in capabilities[capability].get("organization_choices", [])
                ]
            )
        elif dep_category == "jurisdiction":
            dep_choices.extend(
                [
                    {item.get("include_name"): item.get("description")}
                    for item in capabilities[capability].get("jurisdiction_choices", [])
                ]
            )

    return list(unique_everseen(dep_choices))


def get_pypi_deps_from_choices(choices: Union[List[str], DADict]):
    """Gets the Pypi dependency requirement (i.e. docassemble.AssemblyLine>=2.0.19)
    from some chosen dependencies"""
    pypi_deps = []
    if isinstance(choices, DADict):
        choice_list = choices.true_values()
    else:  # List
        choice_list = choices

    capabilities = _get_capabilities()

    for capability in capabilities:
        pypi_deps.extend(
            [
                choice.get("dependency")
                for choice in capabilities[capability].get("organization_choices", [])
                + capabilities[capability].get("jurisdiction_choices", [])
                if choice.get("dependency")
                and choice.get("include_name") in choice_list
            ]
        )

    return list(unique_everseen(pypi_deps))


def get_yml_deps_from_choices(choices: Union[List[str], DADict]):
    """Gets the yml file (i.e. docassemble.AssemblyLine:data/question/ql_baseline.yml)
    from some chosen dependencies"""
    # TODO
    # We might want to prefix choices with the name of the package, and if so this would break
    if isinstance(choices, DADict):
        return choices.true_values()
    else:  # List
        return choices


def get_full_dep_details(dep_category: Optional[str] = None) -> List:
    """Get the full dictionary describing each dependency (including custom ones) so that it can be
    filtered and used as needed."""
    dep_choices = []

    capabilities = _get_capabilities()

    # TODO: do we want to prefix the choice with the package name?
    for capability in capabilities:
        if dep_category == "organization":
            dep_choices.extend(capabilities[capability].get("organization_choices", []))
        elif dep_category == "jurisdiction":
            dep_choices.extend(capabilities[capability].get("jurisdiction_choices", []))

    return list(unique_everseen(dep_choices))


def get_matching_deps(
    dep_category: Optional[str] = None, state: Optional[str] = None
) -> DADict:
    """Get the dependencies that match the specified state.
    State "ANY" has a special meaning."""
    dep_choices = []

    # TODO: do we want to prefix the choice with the package name?
    capabilities = _get_capabilities()

    for capability in capabilities.values():
        if dep_category == "organization":
            dep_choices.extend(
                [
                    item.get("include_name")
                    for item in capability.get("organization_choices", [])
                    if item.get("state", "").lower() == str(state).lower()
                ]
            )
        elif dep_category == "jurisdiction":
            dep_choices.extend(
                [
                    item.get("include_name")
                    for item in capability.get("jurisdiction_choices", [])
                    if item.get("state", "").lower() == str(state).lower()
                ]
            )

    if len(dep_choices) > 0 or str(state).lower() == "any":
        return DADict(
            elements={item: True for item in unique_everseen(dep_choices)},
            auto_gather=False,
            gathered=True,
        )

    return get_matching_deps(dep_category=dep_category, state="ANY")


def get_output_mako_choices() -> Dict[str, str]:
    """
    Get a dictionary with all available templates for generating
    the interview YAML file. It will be one deep.
    """
    choices = {}
    capabilities = _get_capabilities()

    for key, capability in capabilities.items():
        if capability.get("output_mako"):
            if isinstance(capability["output_mako"], str):
                choices[key] = capability["output_mako"]
            elif isinstance(capability["output_mako"], dict):
                # Flatten the dictionary for easier selection
                for sub in capability["output_mako"]:
                    choices[f"{key}:{sub}"] = capability["output_mako"][sub]
    return choices


def get_output_mako_package_and_path(key: str) -> str:
    """
    Convert a key like Default configuration:standard AssemblyLine or
    docassemble.ILAO:ILAO_output.mako into the canonical path
    for the specified output.mako file on the server, based on the
    published server capabilities.
    """
    choice = get_output_mako_choices().get(key)
    if not choice:
        return "output.mako"  # if lookup fails use the stock template

    if key.startswith("Default configuration:"):
        return choice  # Use the current package

    return f"{key.split(':')[0]}:data/templates/{choice}"


def advertise_capabilities(
    package_name: Optional[str] = None,
    yaml_name: str = "configuration_capabilities.yml",
    base: str = "docassemble.ALWeaver",
    minimum_version="1.5",
):
    """
    Tell the server that the current Docassemble package contains a
    configuration_capabilities.yml file with settings that ALWeaver can use, by
    adding an entry to the global DAStore.

    Defaults to work with standard Docassemble package names. If the package_name
    has 3 parts or more, the last part will be dropped. E.g., it will advertise
    "docassemble.ALWeaver", not "docassemble.ALWeaver.custom_values".

    This function should be imported and run inside any Docassemble package that
    contains settings that you want to advertise to the installed Weaver on a
    given server. This function should be set to run with a # pre-load hook so it
    advertises itself on each server uwsgi reset.

    Example of an `advertise_capabilities.py` file you can include in your own package:
    ```python
    # pre-load

    import os
    from docassemble.ALWeaver.custom_values import advertise_capabilities

    if not os.environ.get('ISUNITTEST'):
      advertise_capabilities(__name__, minimum_version="1.5")
    ```
    """
    weaverdata = DAStore("weaverdata", base=base)
    if not package_name:
        package_name = _package_name()
    elif isinstance(package_name, str):
        package_name_parts = package_name.split(".")
        if len(package_name_parts) > 2:
            package_name = ".".join(package_name_parts[:-1])
    published_configuration_capabilities = (
        weaverdata.get("published_configuration_capabilities") or {}
    )
    if not isinstance(published_configuration_capabilities, dict):
        published_configuration_capabilities = {}
    published_configuration_capabilities[package_name] = [yaml_name, minimum_version]
    weaverdata.set(
        "published_configuration_capabilities", published_configuration_capabilities
    )
    global _CAPABILITY_LOAD_DEFAULTS
    _CAPABILITY_LOAD_DEFAULTS = {
        **_CAPABILITY_LOAD_DEFAULTS,
        "base": base,
        "minimum_version": minimum_version,
    }
    _get_capabilities(refresh=True)
