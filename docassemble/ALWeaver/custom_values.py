# pre-load
from typing import List, Union
from pathlib import Path
import ruamel.yaml as yaml
from docassemble.base.util import log, DADict, DAList, user_info, DAStore, path_and_mimetype
from docassemble.base.core import objects_from_file
# TODO(brycew): is this too deep into DA? Unclear if there are options to write
# sources files to a package while it's running.
import ruamel.yaml as yaml
import sys
from docassemble.base.functions import package_data_filename
from packaging.version import Version
import os

"""
Container for widely used data that may be altered by user inputs.
"""

__all__ = ['get_possible_deps_as_choices', 'get_pypi_deps_from_choices', 
           'get_yml_deps_from_choices', 'SettingsList', 'load_capabilities']

class SettingsList(DAList):
  """
  A simple list that can sync itself to a DAStore
  """
  def init(self, *pargs, **kwargs):
    super().init(*pargs, **kwargs)

  def hook_after_gather(self):
    if hasattr(self, 'store'):
      self.store.set(self.instanceName, self)
  
  def __str__(self):
    return "\n".join(self.complete_elements())


################################# Old stuff to refactor
class Object(object):
  pass

custom_values = Object()
# This is to workaround fact you can't do local import in Docassemble playground

# Var names of people-type lists that developers add while using the weaver.
# Could be a list, but a dict will match RESERVED_PLURALIZERS_MAP in the
# places it's used, so maybe easier to treat them both the same.
custom_values.people_plurals_map = {}

# Filled in by load_org_specific. Is a dictionary of configs that each org using
# the Weaver can set, per installation. The specific configs are:
# * jurisdiction_dependency_choices: a collection of other yaml files 
#   that the generated interview will include, specifically a jurisdiction
#   It's a map from keys, what the user will see when selecting dependencies, that maps to
#   a list of 3 items: the pypi dependency, the yaml include, and a boolean for default selection
custom_values.org_specific_config = None

############################# End old stuff

def get_possible_deps_as_choices(dep_category=None, all_custom=custom_values):
  """Gets the possible yml files that the generated interview will depend on"""
  
  dep_choices = []
  all_capabilities = load_capabilities()
  for capability in all_capabilities:
    if dep_category == 'organization':
      dep_choices.extend([
        {item.get('include_name'): item.get('description')}
        for item in all_capabilities[capability].get('organization_choices',[])
      ])
    elif dep_category == 'jurisdiction':
      dep_choices.extend([
        {item.get('include_name'): item.get('description')}
        for item in all_capabilities[capability].get('jurisdiction_choices',[])
      ])

  return dep_choices
  
  # load_org_specific(all_custom)
  # dep_choices = all_custom.org_specific_config['dependency_choices']
  # if dep_category is None:
  #   return [{dep_key: dep_key, 'default': dep[3]} for dep_key, dep in dep_choices.items()]
  # else:
  #   return [{dep_key: dep_key, 'default': dep[3]} for dep_key, dep in dep_choices.items() 
  #           if dep[2].lower() == dep_category.lower()]

def get_pypi_deps_from_choices(choices:Union[List[str], DADict],
    all_custom=custom_values):
  """Gets the Pypi dependency requirement (i.e. docassemble.AssemblyLine>=2.0.19)
  from some chosen dependencies"""
  return get_values_from_choices(choices, 0)

def get_yml_deps_from_choices(choices:Union[List[str], DADict],
    all_custom_values=custom_values):
  """Gets the yml file (i.e. docassemble.AssemblyLine:data/question/ql_baseline.yml)
  from some chosen dependencies"""
  return get_values_from_choices(choices, 1)

def get_values_from_choices(choices:Union[List[str], DADict], value_idx:int=0,
    all_custom_values=custom_values):
  load_org_specific(all_custom_values)
  if isinstance(choices, DADict):
    choice_list = choices.true_values()
  else: # List
    choice_list = choices
  
  return [all_custom_values.org_specific_config['dependency_choices'][chosen_val][value_idx]
      for chosen_val in choice_list]

######################## pre load ###############################
# This runs each time the .py file runs, which should be on each uwsgi reset

def load_capabilities(base:str="docassemble.ALWeaver", minimum_version="1.5", include_playground=False):
  # Get the contents of the current package's capabilities file.
  # The local capabilities will always be the default configuration
  this_yaml = path_and_mimetype("data/sources/configuration_capabilities.yml")[0]
  weaverdata = DAStore(base=base)
  published_configuration_capabilities = weaverdata.get("published_configuration_capabilities") or {}
  
  with open(this_yaml) as f:
    this_yaml_contents = f.read()

  first_file = list(yaml.safe_load_all(this_yaml_contents))[0]
  
  capabilities = {"Default configuration": first_file}
  
  for key in list(published_configuration_capabilities.keys()):
    # Filter configurations based on minimum published version
    if isinstance(published_configuration_capabilities[key], tuple) and Version(published_configuration_capabilities[key][1]) < Version(minimum_version):
      log("Skipping published weaver configuration {key}:{published_configuration_capabilities[key]} because it is below the minimum version {minimum_version}. Consider updating the {key} package.")
      del published_configuration_capabilities[key]
    # Filter out capability files unless the package is installed system-wide
    if not include_playground and key.startswith("docassemble.playground"):
      del published_configuration_capabilities[key]
  
  current_package_name = __name__
  for package_name in published_configuration_capabilities:
    # Don't add the current package twice
    if not current_package_name == package_name:
      path = path_and_mimetype(f"{package_name}:data/sources/{published_configuration_capabilities[package_name][0]}")
      try:
        with open(path) as f:
          yaml_contents = f.read()
        capabilities[package_name] = list(yaml.safe_load_all(yaml_contents))[0]
      except:
        log(f"Unable to load published Weaver configuration file {path}")
  
  return capabilities
      
def _load_templates(self, template_path:str)->None:
    """
    Load YAML file with Mako templates into the templates attribute.
    Overwrites any existing templates.
    """
    path = path_and_mimetype(template_path)[0]
    with open(path) as f:
      contents = f.read()
    self.templates = list(yaml.safe_load_all(contents))[0] # Take the first YAML "document"    

def advertise_capabilities(package_name:str=None, yaml_name:str="configuration_capabilities.yml", base:str="docassemble.ALWeaver", minimum_version="1.5"):
  weaverdata = DAStore(base=base)
  if not package_name:
    package_name = __name__
  published_configuration_capabilities = weaverdata.get("published_configuration_capabilities") or {}
  published_configuration_capabilities[package_name] = (yaml_name, minimum_version)
  weaverdata.set('published_configuration_capabilities', published_configuration_capabilities)
  
if not __name__ == '__main__' and not os.environ.get('ISUNITTEST'):
  advertise_capabilities()