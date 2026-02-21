Always use a local venv before trying any Python tests.
Check in .venv as well as ~/venv

After every change, you can use dayamlchecker to validate YAML syntax.

You should run tests interactively covering these patterns:

1. Unlabeled Word document
2. Unlabeled PDF document
3. Labeled PDF document
4. Labeled Word document

Also try with/without LLM assistance and with/without "auto drafting/I'm feeling lucky" mode enabled.

When modifying this repository, you should use the Docassemble API
to test that your changes work.

Look for an existing docassemblecli installation in ~/.docassemblecli, likely apps-dev.suffoklitlab.org

You can directly use docassemblecli

You can use the bearer token in the header as X-API-Key along with
the API request.

Always install your test to a playground project with the name
Weaver and the branchname, using CamelCase as no non-letter
characters are allowed.

Then run the test via server.com/start/playground[my user ID]/assembly_line