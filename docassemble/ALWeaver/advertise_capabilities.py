# pre-load

import os
from docassemble.base.util import DAStore, log

__all__ = ['advertise_capabilities']

def _package_name():
  """Get package name without the name of the current module, like: docassemble.ALWeaver instead of
  docassemble.ALWeaver.advertise_capabilities"""
  try:
    return ".".join(__name__.split(".")[:-1])
  except:
    return __name__

def advertise_capabilities(package_name:str=None, yaml_name:str="configuration_capabilities.yml", base:str="docassemble.ALWeaver", minimum_version="1.5"):
  """
  Tell the server that the current Docassemble package contains a configuration_capabilities.yml file with settings that
  ALWeaver can use, by adding an entry to the global DAStore. This function should be set to run with a 
  # pre-load hook so it advertises itself on each server uwsgi reset.
  """
  weaverdata = DAStore(base=base)
  if not package_name:
    package_name = _package_name()    
  published_configuration_capabilities = weaverdata.get("published_configuration_capabilities") or {}
  if not isinstance(published_configuration_capabilities, dict):
    published_configuration_capabilities = {}
  published_configuration_capabilities[package_name] = [yaml_name, minimum_version]
  weaverdata.set('published_configuration_capabilities', published_configuration_capabilities)
  
# If you want to prevent this script from running in unittests, add an environment variable ISUNITTEST set to TRUE  
if not os.environ.get('ISUNITTEST'):
  advertise_capabilities() 