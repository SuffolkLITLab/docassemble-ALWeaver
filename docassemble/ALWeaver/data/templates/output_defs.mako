<%doc>

    Reusable macros (mako defs) for generating Docassemble YAML files.

</%doc>\
<%
    from more_itertools import unique_everseen
%>\
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
</%def>\
<%def name="review_yaml(collection)">\
  % if collection.var_type == "list":
  - Edit: ${ collection.var_name }.revisit
  % else:
  - Edit: ${ collection.var_name }
  % endif
    button: |
      % if collection.var_type == "list":
      **${ collection.var_name.capitalize().replace("_", " ") }**

      <%text>%</%text> for item in ${ collection.var_name }:
        * $<%text>{</%text> item }
      <%text>%</%text> endfor
      % elif collection.var_type == "object":
      **${ collection.var_name.capitalize().replace("_", " ") }**
  
      % for att, disp_set in collection.attribute_map.items():
      <%text>%</%text> if defined("${ collection.var_name }.${ disp_set[1] }"):
      * ${ att }: <%text>${</%text> ${ collection.var_name }.${ disp_set[0] } <%text>}</%text>
      <%text>%</%text> endif
      % endfor
      % else:
      % if hasattr(collection.fields[0], "label"):
      **${ collection.fields[0].label }**:
      % else:
      **${ collection.fields[0].get_settable_var() }**:
      % endif # has a label
      % if hasattr(collection.fields[0], "field_type"):
      % if collection.fields[0].field_type in ["yesno", "yesnomaybe"]:
      <%text>${</%text> word(yesno(${ collection.full_display() })) }
      % elif collection.fields[0].field_type in ["integer", "number", "range", "date"]:
      <%text>${</%text> ${ collection.full_display() } }
      % elif collection.fields[0].field_type == "area":
      > <%text>${</%text> single_paragraph(${ collection.full_display() }) }
      % elif collection.fields[0].field_type == "file": # add an extra newline for images

      <%text>${</%text> ${ collection.full_display() } }
      % elif collection.fields[0].field_type == "currency":
      <%text>${</%text> currency(${ collection.full_display() }) }
      % else:
      <%text>${</%text> ${ collection.full_display() } }
      % endif
      % else: # No field type
      <%text>${</%text> ${ collection.fields[0].final_display_var } }
      % endif # has field type
      % endif # collection.var_type
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
% if len(collection.attribute_map) == 0:
edit: True
% else:
edit:
  % for disp_and_set in collection.attribute_map.values():
  - ${ disp_and_set[1] }
  % endfor
% endif
confirm: True\
</%def>\
<%def name="attachment_yaml(field, attachment_name)">\
% if hasattr(field, "paired_yesno") and field.paired_yesno:
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
      - "${ raw_name }": <%text>${</%text> ${ attachment_name }.safe_value("${ field.final_display_var }") }
      % else:
      - "${ raw_name }": <%text>${</%text> ${ field.final_display_var } }
      % endif
    % endif
  % endfor
% endif
</%def>