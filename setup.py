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

setup(name='docassemble.assemblylinewizard',
      version='0.37',
      description=(''),
      long_description='# docassemble.assemblylinewizard\r\n\r\n## Developing Tests\r\n\r\nTo write and run the tests, you\'ll need to set up your testing environment in Python.\r\nBe forewarned, as part of the requirements,\r\nyou have to install the `docassemble` package, which is complex. If you have trouble downloading that\r\npackage, take a look at the [installation instructions](https://docassemble.org/docs/installation.html)\r\nor post your question in the [Docassemble Slack channel](docassemble.slack.com).\r\n\r\n### Set up a virtual environment\r\n\r\nFirst, set up a virtual environment called `docassemble` to hold all the packages\r\nrelated to this repository.\r\nThis will keep your code clean, and make sure this repository does not interfere with\r\nyour other projects.\r\n\r\n```\r\n$ cd docassemble/assemblylinewizard\r\n$ pip3 install virtualenv\r\n$ virtualenv -p $(which python3) docassemble\r\n$ source docassemble/bin/activate\r\n$ pip install -r requirements.txt\r\n```\r\n\r\n(I used `pip3` and `python3` above, because I have both Python 2 and Python 3 on my machine, but you\r\ncan use just `pip` and `python` if you only have Python 3.)\r\n\r\nIf your errors show something like `mysql_config: command not found` it means you\'re missing\r\n`mysql`, which is a dependency. You can search how to install it for your system.\r\n\r\nThen, everytime you work on this project, enter your virtual environment with\r\n\r\n```\r\n$ source docassemble/bin/activate\r\n```\r\n\r\nand everytime you finish working on this project, exit your virtual environment with\r\n\r\n```\r\n$ deactivate\r\n```\r\n\r\n### Run the tests\r\n\r\nTo run the tests, make sure you are in the directory with the tests (i.e., `docassemble/assemblylinewizard`)\r\nand use the following commands (in order of "runs all tests" to "runs one test")\r\n\r\n```\r\n$ python -m unittest discover\r\n$ python -m unittest test_file\r\n$ python -m unittest test_file.TestClass\r\n$ python -m unittest test_file.TestClass.test_method\r\n```\r\n\r\n\r\n## Author\r\n\r\nQuinten Steenhuis, qsteenhuis@suffolk.edu\r\n\r\n',
      long_description_content_type='text/markdown',
      author='Quinten Steenhuis',
      author_email='qsteenhuis@suffolk.edu',
      license='MIT',
      url='https://docassemble.org',
      packages=find_packages(),
      namespace_packages=['docassemble'],
      install_requires=[],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/assemblylinewizard/', package='docassemble.assemblylinewizard'),
     )

