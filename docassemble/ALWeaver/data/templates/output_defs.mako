<%doc>

    Reusable macros (mako defs) for generating Docassemble YAML files.

</%doc>\
<%
    from more_itertools import unique_everseen
%>\
<%def name="field_entry_yaml(field)">\
  - "${ escape_double_quoted_yaml(field.label) if field.has_label else "no label" }": ${ field.get_settable_var() }
  % if hasattr(field, "default"):
    default: ${ repr(field.default) }
  % endif
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
  % if hasattr(field, "is_optional") and field.is_optional:
    required: False
  % endif
</%def>\
<%doc>

    One review entry: either a bulleted summary of a list, or a screen's worth
    of `Label: value` lines under the question that asked for them.

    Every value is written so an undefined variable renders as empty. A review
    screen that forces a definition sends the user back into the interview just
    for looking at their answers, which is what
    https://github.com/SuffolkLITLab/docassemble-ALWeaver/issues/482 is about.

</%doc>\
<%def name="review_yaml(entry)">\
  - Edit: ${ entry.edit_var }
    button: |
      **${ entry.title }**
  % if entry.list_var:

      <%text>%</%text> for item in ${ entry.list_var }:
        * $<%text>{</%text> item }
      <%text>%</%text> endfor
  % else:
    % for row in entry.rows:

      ${ row.label }: <%text>${</%text> ${ row.expression } }
    % endfor
  % endif
</%def>\
<%def name="table_page(collection)">\
---
table: ${ collection.var_name }.table
rows: ${ collection.var_name }
columns:
  % for att, disp_and_set in collection.attribute_map.items():
  - ${ att.capitalize().replace("_", " ") }: |
      row_item.${ disp_and_set[0] } if defined("row_item.${ disp_and_set[1] }") else ""
  % endfor
  % if len(collection.attribute_map) == 0:
  - Name: |
      row_item
  % endif
<%
    edit_attributes = table_edit_attributes(collection)
%>\
% if not edit_attributes:
edit: True
% else:
<%doc>

    Docassemble seeks every variable named under `edit:`, defining any the
    interview never asked. One attribute per group is enough -- the screen that
    sets `name.first` sets the rest of the name with it -- and signatures are
    left out on purpose. See ALWeaver#482.

</%doc>\
edit:
  % for attribute in edit_attributes:
  - ${ attribute }
  % endfor
% endif
confirm: True\
</%def>\
<%def name="attachment_yaml(field, attachment_name)">\
% if field.is_option_group():
      % for raw_name in field.raw_field_names:
      - "${ raw_name }": <%text>${</%text> ${ field.option_fill_expression(raw_name) } }
      % endfor
% elif hasattr(field, "paired_yesno") and field.paired_yesno:
      % for raw_name in field.raw_field_names:
        % if remove_multiple_appearance_indicator(varname(raw_name)).endswith("_yes"):
      - "${ raw_name }": <%text>${</%text> ${ field.final_display_var } }
        % else:
      - "${ raw_name }": <%text>${</%text> not ${ field.final_display_var } }
        % endif # ends with yes
      % endfor
% else:
  % for raw_name in field.raw_field_names: # handle multiple appearance indicators
    % if hasattr(field, "field_type") and field.field_type=="date":
      - "${ raw_name }": <%text>${</%text> ${ field.variable }.format() }
    % elif hasattr(field, "field_type") and field.field_type=="currency":
      - "${ raw_name }": <%text>${</%text> currency(${ field.variable }) }
    % elif hasattr(field, "field_type") and field.field_type=="number":
      - "${ raw_name }": <%text>${</%text> "{:,.2f}".format(${ field.variable }) }
    % elif field.field_type_guess == "signature":
      % if field.final_display_var.endswith("].signature"): # signature of ALIndividual
      - "${ raw_name }": <%text>${</%text> ${ field.final_display_var}_if_final(i) }
      % else: # standalone signature field
      # It's a signature: test which file version this is; leave empty unless it's the final version)
      - "${ raw_name }": <%text>${</%text> ${ field.final_display_var} if i == "final" else '' }
      % endif 
    % else: # all other variable types including text
      % if hasattr(field, "send_to_addendum") and field.send_to_addendum and attachment_name:
      - "${ raw_name }": <%text>${</%text> ${ attachment_name }.safe_value("${ field.final_display_var }"${ field.safe_value_kwargs() }) }
      % else:
      - "${ raw_name }": <%text>${</%text> ${ field.final_display_var } }
      % endif
    % endif
  % endfor
% endif
</%def>
