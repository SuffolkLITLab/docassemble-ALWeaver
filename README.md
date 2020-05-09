# docassemble.assemblylinewizard

## Developing Tests

To write and run the tests, you'll need to set up your testing environment in Python.
Be forewarned, as part of the requirements,
you have to install the `docassemble` package, which is complex. If you have trouble downloading that
package, take a look at the [installation instructions](https://docassemble.org/docs/installation.html)
or post your question in the [Docassemble Slack channel](docassemble.slack.com).

### Set up a virtual environment

First, set up a virtual environment called `docassemble` to hold all the packages
related to this repository.
This will keep your code clean, and make sure this repository does not interfere with
your other projects.

```
$ cd docassemble/assemblylinewizard
$ pip3 install virtualenv
$ virtualenv -p $(which python3) docassemble
$ source docassemble/bin/activate
$ pip install -r requirements.txt
```

(I used `pip3` and `python3` above, because I have both Python 2 and Python 3 on my machine, but you
can use just `pip` and `python` if you only have Python 3.)

If your errors show something like `mysql_config: command not found` it means you're missing
`mysql`, which is a dependency. You can search how to install it for your system.

Then, everytime you work on this project, enter your virtual environment with

```
$ source docassemble/bin/activate
```

and everytime you finish working on this project, exit your virtual environment with

```
$ deactivate
```

### Run the tests

To run the tests, make sure you are in the directory with the tests (i.e., `docassemble/assemblylinewizard`)
and use the following commands (in order of "runs all tests" to "runs one test")

```
$ python -m unittest discover
$ python -m unittest test_file
$ python -m unittest test_file.TestClass
$ python -m unittest test_file.TestClass.test_method
```


## Author

Quinten Steenhuis, qsteenhuis@suffolk.edu

