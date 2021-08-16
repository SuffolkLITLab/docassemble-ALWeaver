import os
import sys
from setuptools import setup, find_packages
from fnmatch import fnmatchcase
from distutils.util import convert_path

standard_exclude = ('*.pyc', '*~', '.*', '*.bak', '*.swp*')
standard_exclude_directories = ('.*', 'CVS', '_darcs', './build', './dist', 'EGG-INFO', '*.egg-info')
def find_package_data(where='.', package='', exclude=standard_exclude, exclude_directories=standard_exclude_directories):
    out = {}
    stack = [(convert_path(where), '', package)]
    while stack:
        where, prefix, package = stack.pop(0)
        for name in os.listdir(where):
            fn = os.path.join(where, name)
            if os.path.isdir(fn):
                bad_name = False
                for pattern in exclude_directories:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                if os.path.isfile(os.path.join(fn, '__init__.py')):
                    if not package:
                        new_package = name
                    else:
                        new_package = package + '.' + name
                        stack.append((fn, '', new_package))
                else:
                    stack.append((fn, prefix + name + '/', package))
            else:
                bad_name = False
                for pattern in exclude:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                out.setdefault(package, []).append(prefix+name)
    return out

setup(name='docassemble.ALWeaver',
      version='1.0.3',
      description=(''),
      long_description='# Assembly Line Weaver\r\n\r\nA tool to help generate draft interviews for the docassemble platform. Tightly linked to https://github.com/SuffolkLITLab/docassemble-AssemblyLine. Currently linked to https://github.com/SuffolkLITLab/docassemble-MassAccess but moving to be more jurisdiction independent.\r\n\r\n## History\r\n\r\n* 2021-04-14 Multiple fixes:\r\n    * Migrated to more flexible Mako template structure for generated \r\n      interview blocks\r\n    * Package can be installed (for test purposes) after being\r\n      generated\r\n    * Various refactors and code cleanup\r\n    * Simplified and improved generated code and order of blocks\r\n    * Added version number/date stamp to generated code\r\n\r\n* 2021-03-09 Extensive improvements:\r\n    * Improvements to review screens\r\n    * Question/field editing and reordering\r\n    * Improvements to YAML structure\r\n    * Generate interstitial screens\r\n    * Refactoring and bug fixes\r\n* 2021-02-09 Combine yes/no variables; more flexible handling of people variables and assistance with gathering varying numbers w/ less code\r\n* 2021-01-29 Bug fixes; migration to AssemblyLine complete\r\n* 2021-01-25 Bug fixes, start migration to [AssemblyLine](https://github.com/SuffolkLITLab/docassemble-AssemblyLine) dependency and away from MAVirtualCourt\r\n\r\n## Authors\r\n\r\nQuinten Steenhuis, qsteenhuis@suffolk.edu  \r\nMichelle  \r\nBryce Willey  \r\nLily  \r\nDavid Colarusso  \r\nNharika Singh  \r\n\r\n## Installation requirements\r\n\r\n* Create a Docassemble API key and add it your configuration like this:\r\n```\r\ninstall packages api key: 123458abcdefghijlklmno99A\r\n```\r\n',
      long_description_content_type='text/markdown',
      author='Quinten Steenhuis',
      author_email='qsteenhuis@suffolk.edu',
      license='MIT',
      url='https://docassemble.org',
      packages=find_packages(),
      namespace_packages=['docassemble'],
      install_requires=['docx2python>=1.27.1'],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/ALWeaver/', package='docassemble.ALWeaver'),
     )

