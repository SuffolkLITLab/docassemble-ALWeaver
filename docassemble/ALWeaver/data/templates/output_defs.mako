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
      * ${ att }: <%text>${</%text>${ collection.var_name }.${ disp_set[0] } <%text>}</%text>
      <%text>%</%text> endif
      % endfor
      % else:
      <%
            settable_var = collection.fields[0].get_settable_var()
            parent_var = DAField._get_parent_variable(settable_var)[0]
            # NOTE: we rely on the "stock" full_display map here
            full_display = substitute_suffix(parent_var)
      %>
      % if hasattr(collection.fields[0], "label"):
      **${ collection.fields[0].label }**:
      % else:
      **${ collection.fields[0].get_settable_var() }**
      % endif # has a label
      % if hasattr(collection.fields[0], "field_type"):
      <% 
          field_type = collection.fields[0].field_type
      %>
      % if field_type in ["yesno", "yesnomaybe"]:
      <%text>${</%text> word(yesno(${ full_display })) }
      % elif field_type in ["integer", "number", "range", "date"]:
      <%text>${</%text> ${ full_display } }
      % elif field_type == "area":
      > <%text>${</%text> single_paragraph(${ full_display }) }
      % elif field_type == "file": # add an extra newline for images

      <%text>${</%text> ${ full_display } }
      % elif field_type == "currency":
      <%text>${</%text> currency(${ full_display }) }
      % else:
      <%text>${</%text> ${ full_display } }
      % endif
      % else: # No field type
      <%text>${</%text> ${ collection.fields[0].final_display_var } }
      % endif # has field type
      % endif # collection.var_type

</%def>