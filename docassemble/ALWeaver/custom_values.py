from typing import List, Union
from pathlib import Path
import yaml
from docassemble.base.util import log, DADict
from docassemble.base.core import objects_from_file
# TODO(brycew): is this too deep into DA? Unclear if there are options to write
# sources files to a package while it's running.
from docassemble.base.functions import package_data_filename

"""
Container for widely used data that may be altered by user inputs.
"""

__all__ = ['get_possible_deps_as_choices', 'get_pypi_deps_from_choices', 
           'get_yml_deps_from_choices']

# This is to workaround fact you can't do local import in Docassemble playground
class Object(object):
  pass

custom_values = Object()

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

def load_org_specific(all_custom_values=custom_values):
  if all_custom_values.org_specific_config is None:
    try:
      all_custom_values.org_specific_config = objects_from_file('org_specific.yml')
    except (FileNotFoundError, SystemError) as ex:
      # Populate some default values
      all_custom_values.org_specific_config = {
        'dependency_choices': {
          'Massachusetts State': 
              ['docassemble.ALMassachusetts>=0.0.7', 
               'docassemble.ALMassachusetts:al_massachusetts.yml',
               'jurisdiction',
               True],
          'MassAccess': 
              ['docassemble.MassAccess',  
               'docassemble.MassAccess:massaccess.yml',
               'organization',
               True]
        }
      }
      to_write = package_data_filename('data/sources/org_specific.yml')
      with open(to_write, 'w') as writ:
        writ.write(yaml.safe_dump(all_custom_values.org_specific_config))

def get_possible_deps_as_choices(dep_category=None, all_custom=custom_values):
  """Gets the possible yml files that the generated interview will depend on"""
  load_org_specific(all_custom)
  dep_choices = all_custom.org_specific_config['dependency_choices']
  if dep_category is None:
    return [{dep_key: dep_key, 'default': dep[3]} for dep_key, dep in dep_choices.items()]
  else:
    return [{dep_key: dep_key, 'default': dep[3]} for dep_key, dep in dep_choices.items() 
            if dep[2].lower() == dep_category.lower()]

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