# pre-load

import os
from docassemble.base.util import DAStore

__all__ = ['advertise_capabilities']

def advertise_capabilities(package_name:str=None, yaml_name:str="configuration_capabilities.yml", base:str="docassemble.ALWeaver", minimum_version="1.5"):
  weaverdata = DAStore(base=base)
  if not package_name:
    package_name = __name__
  published_configuration_capabilities = weaverdata.get("published_configuration_capabilities") or {}
  published_configuration_capabilities[package_name] = (yaml_name, minimum_version)
  weaverdata.set('published_configuration_capabilities', published_configuration_capabilities)
  
# After docassemble.demo.test is removed from #pre-load we can also check 'unittest' in sys.modules.keys()  
if not __name__ == '__main__' and not os.environ.get('ISUNITTEST'):
  advertise_capabilities()