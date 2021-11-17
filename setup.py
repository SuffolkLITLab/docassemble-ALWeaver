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
      version='1.4.4',
      description=(''),
      long_description='# Assembly Line Weaver: Suffolk LIT Lab Document Assembly Line\r\n\r\n<img src="https://user-images.githubusercontent.com/7645641/142245862-c2eb02ab-3090-4e97-9653-bb700bf4c54d.png" alt="drawing" width="300" alt="work together" style="align: center;"/>\r\n\r\nThe Assembly Line Project is a collection of volunteers, students, and institutions who joined together\r\nduring the COVID-19 pandemic to help increase access to the court system. Our vision is mobile-friendly,\r\neasy to use **guided** online forms that help empower litigants to access the court remotely.\r\n\r\nOur signature project is [CourtFormsOnline.org](https://courtformsonline.org).\r\n\r\nWe designed a step-by-step, assembly line style process for automating court forms on top of Docassemble\r\nand built several tools along the way that **you** can use in your home jurisdiction.\r\n\r\nThis package contains an **automation and rapid prototyping tool** to support authoring robust, \r\nconsistent, and attractive Docassemble interviews that help complete court forms. Upload a labeled\r\nPDF or DOCX file, and the Assembly Line Weaver will produce a runnable, clean code, draft of a\r\nDocassemble interview that you can continue to edit and refine.\r\n\r\nRead more on our [documentation page](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/).\r\n\r\n\r\n# Related repositories\r\n\r\n* https://github.com/SuffolkLitLab/docassemble-AssemblyLine\r\n* https://github.com/SuffolkLitLab/docassemble-ALMassachusetts\r\n* https://github.com/SuffolkLitLab/docassemble-MassAccess\r\n* https://github.com/SuffolkLitLab/docassemble-ALGenericJurisdiction\r\n* https://github.com/SuffolkLitLab/EfileProxyServer\r\n\r\n# Documentation\r\n\r\nhttps://suffolklitlab.org/docassemble-AssemblyLine-documentation/\r\n\r\n## History\r\n* 2021-11-03\r\n    * Add support for *plural* names for people in PDF files\r\n\r\n* 2021-10-15\r\n    * Handle overflow in addendum\r\n    * Multiple choice radio/checkbox fields\r\n    * DOCX validation\r\n* 2021-09-09\r\n    * Improved internationalization\r\n    * Simplified PDF checker\r\n* 2021-04-14 Multiple fixes:\r\n    * Migrated to more flexible Mako template structure for generated \r\n      interview blocks\r\n    * Package can be installed (for test purposes) after being\r\n      generated\r\n    * Various refactors and code cleanup\r\n    * Simplified and improved generated code and order of blocks\r\n    * Added version number/date stamp to generated code\r\n\r\n* 2021-03-09 Extensive improvements:\r\n    * Improvements to review screens\r\n    * Question/field editing and reordering\r\n    * Improvements to YAML structure\r\n    * Generate interstitial screens\r\n    * Refactoring and bug fixes\r\n* 2021-02-09 Combine yes/no variables; more flexible handling of people variables and assistance with gathering varying numbers w/ less code\r\n* 2021-01-29 Bug fixes; migration to AssemblyLine complete\r\n* 2021-01-25 Bug fixes, start migration to [AssemblyLine](https://github.com/SuffolkLITLab/docassemble-AssemblyLine) dependency and away from MAVirtualCourt\r\n\r\n## Authors\r\n\r\nQuinten Steenhuis, qsteenhuis@suffolk.edu  \r\nMichelle  \r\nBryce Willey  \r\nLily  \r\nDavid Colarusso  \r\nNharika Singh  \r\n\r\n## Installation requirements\r\n\r\n* Create a Docassemble API key and add it your configuration like this:\r\n```\r\ninstall packages api key: 123458abcdefghijlklmno99A\r\n```\r\n',
      long_description_content_type='text/markdown',
      author='Quinten Steenhuis',
      author_email='qsteenhuis@suffolk.edu',
      license='MIT',
      url='https://docassemble.org',
      packages=find_packages(),
      namespace_packages=['docassemble'],
      install_requires=['PyYAML>=5.1.2', 'docassemble.ALToolbox>=0.2.1', 'docx2python>=1.27.1'],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/ALWeaver/', package='docassemble.ALWeaver'),
     )

