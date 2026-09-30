# Reusable help text in `/al/editor`

Reusable help text is a Docassemble `template:` block, not a Word or PDF file
from the editor's **Templates** workspace. Its subject is the label the user
clicks, and its content is the Markdown shown after the label expands.

To create one on its own, choose **Add a block → Reusable help text**. Give it a
Python-style variable name, an optional subject, and non-empty content.
The content editor supports the same Markdown and Mako insertion tools as a
question's subquestion. A template may insert another template from its content
toolbar.

To use help on a question, open the subquestion toolbar's kebab menu and choose
**Insert collapsible help**. Select a template that has a subject, or create a
new one in the dialog. The editor inserts:

```mako
${ collapse_template(template_name) }
```

The definition remains a separate block, so the same help can be inserted into
multiple questions without copying it. Remove one use by deleting just that
expression from the subquestion. Edit shared text by opening its template block
in the interview outline. The editor prevents renaming or deleting a template
when it is the last definition of its name and the active YAML file contains
direct `collapse_template(name)` references. Language or conditional variants
may share a template name; the insertion picker lists that name once. A template
name cannot collide with a non-template variable, object, or code binding.

Templates that use advanced Docassemble forms such as `content file:`, dotted
names, or indexed/generic names remain available in the YAML source editor.
