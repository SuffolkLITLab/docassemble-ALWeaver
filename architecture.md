# Assembly Line Weaver Architecture

The AssemblyLine Weaver is a collection of Python modules and Docassemble YAML
interviews that provides a step-by-step graphical process for building draft
Docassemble interviews. It is optimized for quickly building a skeleton project.
The assumption is that the most common use cases will be for building court
forms or court-form like automations.

For a high-level overview of the components of the AssemblyLine project, see:
https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/al_project_architecture

## Overview

YAML files contain interactive questions and answers. One Python module contains
a list of strings that are handled specially when recognizing fields in PDF and
Word documents. The remaining modules are used as the engine of the draft
interview automation process. This package also contains tests and templates
that are used to standardize the automation process.

## Key files

### YAML files (in docassemble/ALWeaver/data/questions)

File you should run in the browser:
- `assembly_line.yml` can be run directly on a Docassemble server and references
  the other YAML files in the same directory

Other files:
- `config.yml`: frontend to help developers continue building the configuration
  system (not for end users)
- `docx_field_tester.yml`: logic for DOCX template validation
- `feedback.yml`: Feedback form that lets users report issues on GitHub
  in-context
- `pdf_field_test.yml`: logic for PDF template validation
- `visual.yml`: controls visual elements in the Weaver - essentially a theme

### Source files in docassemble/ALWeaver/data/sources

- `configuration_capabilities.yml`: currently describes the list of optional
  packages someone can install in a generated package with the
  Weaver--envisioned to allow more flexible configuration in the future
- `output_patterns.yml`: this file contains small Mako templates that are used
  to build the YAML file that the Weaver produces. It is set up as a series of
  small templates right now rather a single large template.

This directory also contains test files for unit testing with ALKiln (see below for more information.)

### Static files in docassemble/ALWeaver/data/static

These files are primarily the front-end interface files, including images and
CSS.

The graphical editor treats the Playground YAML source as authoritative. The
metadata source tab saves through `/al/editor/api/file/metadata`, which requires
the revision returned by the file-read endpoint and replaces only existing
`metadata`, `include`, and `default screen parts` document bodies. If those
documents cannot be identified safely, the scoped save is rejected and the user
must use full source mode. This is an interim safeguard pending the general
revisioned source-patch model.

The file-read API exposes interview text as `raw_yaml`; browser downloads
validate that field as a string before creating a file, including when the
source is intentionally empty.

Editor browser requests go through `editor_api_client.js`. The client enforces
same-origin credentials, structured `EditorApiError` failures, JSON response
validation, CSRF and request-ID headers, timeouts, and cancellation of
superseded reads. Write requests are deliberately not cancelled or treated as
stale by default because the server may already have applied them. The editor
announces client errors in an ARIA live alert and prevents superseded reads from
clearing newer interface state.

Unsaved interview edits are tracked by `editor_dirty_state.js` per filename and
block ID, with separate source-dirty and pending-command state. Each loaded file
also has a deep-cloned saved model. Discard restores that model, while a
single-block save updates only that block's dirty state and overlays any other
unsaved local blocks on the fresh server response. Navigation decisions use the
accessible Save/Discard/Stay dialog instead of clearing a global dirty flag.

The `next_steps` DOCX files are templates for "next steps" documents that a user
can print and read after using an interview. They are associated with different
kinds of interviews that the Weaver can produce.

### Python modules

- `interview_generator.py` is the primary module containing most of the Python code used by the Weaver
- `advertise_capabilities.py` is part of the plugin-able configuration system - it tells the server what optional dependencies this Weaver can add to a generated interview file
- `custom_values.py` is used to scan the server for packages that contain custom configuration settings for the Weaver
- `draggable_table.py` is used by the Weaver frontend to allow rearranging long lists of fields
- `field_grouping.py` is a copy of some features from [FormyFyxer](https://github.com/SuffolkLITLab/FormFyxer) that power the "I'm feeling lucky" button (should be deprecated)
- `generator_constants.py` contains several lists of rules for how to transform PDF field names like `users_name_full` into Docassemble objects like `users[0].name`, as well as indicating reserved DOCX variable names that are handled by questions in the AssemblyLine's question library

## Testing

The Weaver has two kinds of test that are currently configured to run on push to
GitHub:

1. Standard unit tests of pure-Python modules
1. Integration tests using the [ALKiln](https://github.com/suffolkLITLab/ALKiln)
   testing framework

Unit tests can be found in docassemble/ALWeaver/. Filenames begin with `test_`.

The integration tests are located in docassemble/ALWeaver/data/sources/ and
filenames ending with .feature will be run as ALKiln tests.

In addition, `generator_test.yml` is an interactive Docassemble interview that
will test the `map_raw_to_final_display()` function from
`interview_generator.py`. This is designed for quick in-browser testing.
