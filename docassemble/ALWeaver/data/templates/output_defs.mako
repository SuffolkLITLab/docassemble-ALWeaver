<%doc>

    Reusable macros (mako defs) for generating Docassemble YAML files.    
    TODO:
    Make defs for the following methods, so we can keep closer to the output file:
        - attachment_yaml
        - table_page
        - field_entry_yaml (done)
        - review_yaml

</%doc>\
<%def name="field_entry_yaml(field)">\
  - "${ escape_double_quoted_yaml(field.label) if field.has_label else "no label" }": ${ field.get_settable_var() }
  % if hasattr(field, "field_type"):
    % if field.field_type in ["yesno", "yesnomaybe","file","yesnoradio","noyes","noyesradio", "integer","currency","email","range","number","date"]:
    datatype: ${ field.field_type }
    % elif field.field_type == "multiple choice radio":
    input type: radio
    % elif field.field_type == "multiple choice checkboxes":
    datatype: checkboxes
    % elif field.field_type == "multiple choice combobox":
    datatype: combobox
    % elif field.field_type == "multiple choice dropdown":
    input type: dropdown
    % elif field.field_type == "multiselect":
    datatype: multiselect
    % elif field.field_type == "area":
    input type: area
    % if field.need_maxlength():
    maxlength: ${ field.maxlength }
    % endif
    % endif
    % if field.field_type in ["integer", "currency"]:
    min: 0
    % endif
    % if field.field_type in ["email", "text"]:
    % if field.need_maxlength():
    maxlength: ${ field.maxlength }
    % endif
    % endif
    % if field.field_type.startswith("multi"):
    choices:
    % for choice in field.choices.splitlines():
    - ${ choice }
    % endfor
    % endif
    % if field.field_type == "range":
    min: ${ field.range_min }
    max: ${ field.range_max }
    step: ${ field.range_step }
    % endif
  % else: # No datatype. maxlength only relevant attribute (but we expect at least `text` datatype in normal situations)
    % if field.need_maxlength():
    maxlength: ${ field.maxlength }
    % endif
  % endif
</%def>