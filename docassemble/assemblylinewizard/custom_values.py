from typing import List, Union
from pathlib import Path
import json
from docassemble.base.util import DADict

"""
Container for widely used data that may be altered by user inputs.
"""

__all__ = ['get_possible_dependencies', 'get_pypi_deps_from_choices', 'get_yml_deps_from_choices', 
           'get_is_default_from_choices']


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
# * dependency choices: a collection of other yaml files that the generated interview will include
#   It's a map from keys, what the user will see when selecting dependencies, that maps to
#   a list of 3 items: the pypi dependency, the yaml include, and a boolean for default selection
custom_values.org_specific_config = None

def load_org_specific(all_custom_values=custom_values):
  if all_custom_values.org_specific_config is None:
    current_dir = Path(__file__).resolve().parent
    config_file = current_dir.joinpath('data/sources/org_specific.cfg')
    if config_file.exists():
      all_custom_values.org_specific_config = json.load(config_file.open())
    else:
      # Populate some default values
      all_custom_values.org_specific_config = {
        'dependency_choices': {
          'Massachusetts State': 
              ['docassemble.ALMassachusetts>=0.0.7', 
               'docassemble.ALMassachusetts:al_massachusetts.yml', 
               True],
          'MassAccess': 
              ['docassemble.MassAccess',  
               'docassemble.MassAccess:massaccess.yml', 
               True]
        }
      }

def get_possible_dependencies(all_custom_values=custom_values):
  """Gets the possible yml files that the generated interview will depend on"""
  load_org_specific(all_custom_values)
  return all_custom_values.org_specific_config['dependency_choices'].keys()


def get_pypi_deps_from_choices(choices:Union[List[str], DADict], 
    all_custom_values=custom_values):
  return get_values_from_choices(choices, 0)

def get_yml_deps_from_choices(choices:Union[List[str], DADict], 
    all_custom_values=custom_values):
  return get_values_from_choices(choices, 1)

def get_is_default_from_choices(all_custom_values=custom_values):
  load_org_specific(all_custom_values)
  return [dependency[0] for dependency in 
      all_custom_values.org_specific_config['dependency_choices'].items() if dependency[1][2]] 

def get_values_from_choices(choices:Union[List[str], DADict], value_idx:int=0,
    all_custom_values=custom_values):
  load_org_specific(all_custom_values)
  if isinstance(choices, DADict):
    choice_list = choices.true_values()
  else: # List
    choice_list = choices
  
  return [all_custom_values.org_specific_config['dependency_choices'][chosen_val][value_idx] 
      for chosen_val in choice_list] 