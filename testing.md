# Testing instructions

## Developing Tests

To write and run the tests, you'll need to set up your testing environment in Python.

### Set up a virtual environment

First, set up a virtual environment in your command prompt called `venv` to hold all the packages related to this repository.
This will keep your code clean, and make sure this repository does not interfere with
your other projects.

Run these lines in your command prompt.

```
pip3 install virtualenv
virtualenv -p $(which python3.8) venv
source venv/bin/activate
pip3 install --upgrade pip
pip3 install -r docassemble.ALWeaver/requirements.txt
pip3 install --editable .
```

<!-- I had to run `virtualenv -p /usr/local/opt/python@3.8/bin/python3 venv` for the second line. I'm on OSX 10.14.5, but I also have a bunch of weird stuff set up in my configs from waaay back. If we can replicate this on a similar system that doesn't have a bunch of configs set for python, we can add this as a visible warning. -->

(I used `pip3` and `python3` above, because I have both Python 2 and Python 3 on my machine, but you
can use just `pip` and `python` if you only have Python 3.)

If your errors show something like `mysql_config: command not found` it means you're missing
`mysql`, which is a dependency. You can search how to install it for your system.

Another common error is something like `ImportError: pycurl: libcurl link-time ssl backend (openssl) is different from compile-time ssl backend (none/other)`. https://stackoverflow.com/a/21099222/14144258 may help give you direction.

If you want to stop here after setup, you can exit the virtual environment with
```
deactivate
```


### Run the tests

Everytime you want to work on testing, enter your virtual environment with

```
$ source venv/bin/activate
```

To run the tests, make sure your command prompt is in your project's directory (`docassemble-ALWeaver`) and run:
```
python3 -m unittest discover
```

You can also run fewer tests by getting more specific with your testing paths. For example, to run just the `test_mapped_scenarios` method in `test_map_names.py`, you can run:
```
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames.test_mapped_scenarios`
```

The lines below are all valid ways to run tests. They are listed in order of "runs all tests" to "runs one test":

```
python3 -m unittest discover
python3 -m unittest docassemble.ALWeaver.test_map_names
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames
python3 -m unittest docassemble.ALWeaver.test_map_names.TestMapNames.test_mapped_scenarios
```

### Stop

Everytime you finish working on testing, exit your virtual environment with

```
$ deactivate
```
