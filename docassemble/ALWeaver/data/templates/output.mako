<%doc>
    Initial metadata and includes
</%doc>
---
include:
  - docassemble.AssemblyLine:assembly_line.yml
  % for include in get_yml_deps_from_choices( interview.jurisdiction_choices.true_values() + interview.org_choices.true_values()):
  - ${ include }
  % endfor
---
metadata:
  title: |
    ${ interview.title }
  short title: |
    ${ interview.short_title }
  % if interview.categories.any_true():
  tags:
    % for category in interview.categories.true_values():
    - ${ category }
    % endfor
  % endif
  authors:
    % for author in interview.author.splitlines():
    - ${ author }
    % endfor
---
mandatory: True
comment: |
  Global interview metadata
variable name: interview_metadata["${ interview_label }"]
data:
  al_weaver_version: "${ package_version_number }"
  generated on: "${ today().format("yyyy-MM-dd") }"
  title: >-
    ${ oneline(interview.title) }
  short title: >-
    ${ oneline(interview.short_title) }
  description: |-
${ indent(interview.description, by=4) }
  original_form: >-
${ indent(interview.original_form, by=4) }
  % if len(interview.allowed_courts.true_values()) < 1:
  allowed courts: []
  % else:
  allowed courts: 
    % for court in interview.allowed_courts.true_values():
    - "${ escape_double_quoted_yaml(oneline(court)) }"
    % endfor
  % endif
  % if len(interview.categories.true_values()) < 1:
  categories: []
  % else:
  categories:
    % for category in set(interview.categories.true_values()) - {'Other'}:
    - "${ escape_double_quoted_yaml(oneline(category)) }"
    % endfor
    % if interview.categories['Other']:
    % for category in interview.other_categories.split(','):
    - "${ escape_double_quoted_yaml(oneline(category.strip())) }"
    % endfor
    % endif
  % endif
  % if interview.typical_role:
  typical role: "${ escape_double_quoted_yaml(oneline(interview.typical_role)) }"
  % endif
  generate download screen: ${ generate_download_screen }
---
code: |
  interview_metadata['main_interview_key'] =  '${ interview_label }'
---
code: |
  # This controls the default country and list of states in address field questions
  AL_DEFAULT_COUNTRY = "${ interview.default_country_code }"
---
code: |
  # This controls the default state in address field questions
  AL_DEFAULT_STATE = "${ interview.state }"
---
code: |
  github_repo_name =  'docassemble-${ package_title }'
% if defined('interview_intro_prompt'):
---
code: |
  interview_short_title = "${ escape_quotes(interview_intro_prompt) }"
% endif
% if generate_download_screen:
---
code: |
  al_form_type = "${ interview.form_type }" 
% endif
% if len(objects) > 0:
---
objects:
  % for object in objects:
  - ${ object.name }: ${ object.type }${ using_string(object.params) }
  % endfor
% endif
---
sections:
  - review_${ interview_label }: Review your answers
---
#################### Interview order #####################
comment: |
  Controls order and branching logic for questions specific to this form
id: interview_order_${ interview_label }
code: |
  % for field in list(unique_everseen(logic_list)):
  ${ field }
  % endfor
  interview_order_${ interview_label } = True
---
###################### Main order ######################
comment: |
  This block includes the logic for standalone interviews.
  Delete mandatory: True to include in another interview
mandatory: True
code: |
  al_intro_screen
  ${ interview_label }_intro
  interview_order_${ interview_label }
  % if generate_download_screen:
  signature_date
  # Store anonymous data for analytics / statistics
  store_variables_snapshot(
      persistent=True,
      data={
          "zip": showifdef("users[0].address.zip"),
          "reached_interview_end": True,
      },
  )
  % if len(built_in_signatures) > 0:
  ${ interview_label }_preview_question
  basic_questions_signature_flow    
  % for signature_field in built_in_signatures:
  ${ signature_field }
  % endfor
  % endif
  ${ interview_label }_download
  % else:
  ${ interview_label }_thank_you
  % endif
<%doc>
    Question blocks
</%doc>\
<%doc>
    TODO(qs): 
      - add _intro to question ID (after finished testing equivalence to output_patterns.yml)
      - just use interview_label instead of varname(interview.title)
</%doc>\
---
comment: |
  This question is used to introduce your interview. Please customize
id: ${ varname(interview.title) }
continue button field: ${ interview_label }_intro
question: |
  ${ interview.title }
subquestion: |
${ indent(interview.getting_started, 2) }
<%doc>
    Main question loop
</%doc>\
% for question in questions:
---
id: ${ fix_id(question.question_text) }
question: |
${ indent(question.question_text,2) }
% if question.subquestion_text:
subquestion: |
${ indent(question.subquestion_text,2) }
% endif
% if len(question.field_list) > 0:
fields:
  % for field in question.field_list:
${ field_entry_yaml(field) }\
  % endfor
% endif
% if question.needs_continue_button_field:
continue button field: ${ varname(question.question_text) }
% endif
% endfor
<%doc>
    End question loop
</%doc>\
% if generate_download_screen:
---
id: preview ${interview_label }
question: |
  Preview your form before you sign it
subquestion: |
  Here is a preview of the form you will sign on the next page.   
  
  % if interview.court_related:
  <%text>${</%text> al_court_bundle.as_pdf(key='preview') <%text>}</%text>
  % else:
  <%text>${</%text> al_recipient_bundle.as_pdf(key='preview') <%text>}</%text>
  % endif

  Click the image to open it in a new tab. Click the "Edit answers" button
  to edit your answers.

  <%text>${</%text> action_button_html(url_action('review_${ interview_label }'), label='Edit answers', color='info') <%text>}</%text>
  
  Remember to come back to this window to continue and sign your form.
continue button field: ${ interview_label }_preview_question    
% endif
<%doc>
    TODO(qs): signature fields shouldn't depend on whether we have a download screen
</%doc>\
% if generate_download_screen:
---
code: |
  signature_fields = ${ str(list(built_in_signatures) + [field.trigger_gather() for field in all_fields.signatures()] ) }
% endif
% for field in all_fields.skip_fields():
---
code: |
  ${ field.variable } = DAEmpty()
% endfor
% for field in all_fields.code_fields():
---
code: |
  ${ field.variable } = ${ field.code }
% endfor
% if interview.court_related:
---
code: |
  # This is a placeholder for the addresses that will be searched
  # for matching address to court. Edit if court venue is based on 
  # a different address than the user's
  addresses_to_search = [user.address for user in users]
% endif
<%doc>
    Review screens

    TODO(qs): why use fix_id here?
</%doc>\
---
id: ${ fix_id(interview_label) } review screen
event: review_${ interview_label }
question: |
  Review your answers
review:
  % for coll in all_fields.find_parent_collections():
${ review_yaml(coll) | trim }\
  % endfor
% for coll in all_fields.find_parent_collections():
  % if coll.var_type == 'list':
---
continue button field: ${ coll.var_name }.revisit
question: |
  Edit ${ coll.var_name }
subquestion: |
  ${ "${ " + coll.var_name + ".table }" }

  ${ "${ " + coll.var_name + ".add_action() }" }
${ table_page(coll) }

  % endif
% endfor
<%doc>
    If output is a file, generate preview and download screens
    TODO(qs): Move these to question area, instead of after review screen
</%doc>\
% if generate_download_screen:
---
id: download ${ interview_label }
event: ${ interview_label }_download
question: |
  All done
subquestion: |
  Thank you <%text>${users}</%text>. Your form is ready to download and deliver.
  
  View, download and send your form below. Click the "Edit answers" button to fix any mistakes.

  <%text>${</%text> action_button_html(url_action('review_${ interview_label }'), label='Edit answers', color='info') <%text>}</%text>
  
  <%text>
  ${ al_user_bundle.download_list_html() }
  </%text>

  <%text>${</%text> al_user_bundle.send_button_html(show_editable_checkbox=${False if any(map(lambda templ: templ.mimetype == "application/pdf", template_upload)) else True}) <%text>}</%text>

progress: 100
<%doc>
    Else, if no file output and just saving to database:
    generate a thank you page and code blocks for saving data to database
</%doc>\
% else:
---
id: thank you
event: ${ interview_label }_thank_you
question: |
  Thank You!
subquestion: |
  Thank you for submitting your answers! We appreciate your time. 
  
  A copy of your answers was saved in our database.

progress: 100
---
variable name: input_fields_dict
data from code:
  % for field in all_fields.elements:
  "${ field.get_settable_var() }": showifdef("${ field.get_settable_var() }")
  % endfor
---
code: |
  save_input_data(title = "${ interview_label }", input_dict = input_fields_dict)
  saved_report_data = True
% endif
<%doc>
    End alternative end screen (if no file output)
</%doc>\
<%doc>
    Last blocks are only used if we're downloading a file at the end:
    - ALDocument and ALDocument bundle object blocks
    - Attachment block
    - Addendum
</%doc>\
% if generate_download_screen:
<%doc>
    Attachment variables
</%doc>\
---
objects:
  % for v in labels_lists:
  - ${ v.attachment_varname }: ALDocument.using(title="${ v.description }", filename="${ v.input_filename }", enabled=True, has_addendum=${ v.has_addendum }, default_overflow_message=AL_DEFAULT_OVERFLOW_MESSAGE)
  % endfor
---
objects:
  % for bundle in bundles:
  - ${ bundle.name }: ALDocumentBundle.using(elements=[${ ",".join([item.attachment_varname for item in bundle.elements]) }], filename="${ bundle_name }", title="All forms to download for your records", enabled=True)
  % endfor
---
attachments:
  % for v in labels_lists:  
  - name: ${ v.attachment_varname.replace('_',' ') }
    filename: ${ v.output_filename }     
    variable name: ${ v.attachment_varname }[i]        
  % if v.type == 'md':
    content: |
  ${ indent(content, 6) }
  % elif v.type == 'pdf':
    skip undefined: True
    pdf template file: ${ v.input_filename }
    fields:
    % for field in v.fields:
${ attachment_yaml(field, attachment_name=v.attachment_varname) }\
    % endfor
  % else: 
    skip undefined: True
    docx template file: ${ v.input_filename }
  % endif	    
  % endfor
% if all_fields.has_addendum_fields():
---
code: |
  % for field in all_fields.addendum_fields():
  ${ attachment_variable_name }.overflow_fields["${ field.variable }"].overflow_trigger = ${ field.maxlength }
  ${ attachment_variable_name }.overflow_fields["${ field.variable }"].label = "${ field.label }"
  % endfor
  ${ attachment_variable_name }.overflow_fields.gathered = True
  % endif
<%doc>
    End optional addendum code block    
</%doc>
% endif
<%doc>
    End optional blocks related to attachments (if generating a file as output)
</%doc>
