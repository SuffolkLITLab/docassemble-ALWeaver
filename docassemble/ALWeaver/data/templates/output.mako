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
  title: >-
    ${ interview.title }
  short title: >-
    ${ interview.short_title }
  description: |-
${ indent(interview.description, by=4) }
  % if interview.categories.any_true():
  tags:
    % for category in sorted(set(interview.categories.true_values())):
    - "${ escape_double_quoted_yaml(oneline(category)) }"
    % endfor
    % if interview.has_other_categories:
    % for category in interview.other_categories.split(','):
    - "${ escape_double_quoted_yaml(oneline(category.strip())) }"
    % endfor
    % endif
  % else:
  tags: []
  % endif
  authors:
    % for author in interview.author.splitlines():
    - ${ author }
    % endfor
  % if interview.original_form:
  original_form:
    - ${ interview.original_form }
  % endif
  % if interview.help_page_url:
  help_page_url: >-
${ indent(interview.help_page_url, by=4) }
  help_page_title: >-
${ indent(interview.help_page_title, by=4) }
  % endif
  % if len(interview.allowed_courts.true_values()) < 1:
  allowed_courts: []
  % else:
  allowed_courts: 
    % for court in sorted(interview.allowed_courts.true_values() + (interview.allowed_courts_text.split(",") if interview.allowed_courts.get("Other") else [])):
    - "${ escape_double_quoted_yaml(oneline(court)) }"
    % endfor
  % endif
  % if interview.typical_role:
  typical_role: "${ escape_double_quoted_yaml(oneline(interview.typical_role)) }"
  % endif
  al_weaver_version: "${ package_version_number }"
  generated_on: "${ today().format("yyyy-MM-dd") }"
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
  github_repo_name =  'docassemble-${ interview.package_title }'
% if defined('interview.intro_prompt'):
---
code: |
  interview_short_title = "${ escape_quotes(interview.intro_prompt) }"
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
  - review_${ interview.interview_label }: Review your answers
---
#################### Interview order #####################
comment: |
  Controls order and branching logic for questions specific to this form
id: interview_order_${ interview.interview_label }
code: |
  % if generate_download_screen:
  # Set the allowed courts for this interview
  % if interview.court_related:
  allowed_courts = ${ repr(sorted(interview.allowed_courts.true_values() + (interview.allowed_courts_text.split(",") if interview.allowed_courts.get("Other") else []))) }
  % endif
  % endif
  nav.set_section("review_${ interview.interview_label }")
  % if interview.typical_role == 'unknown':
  # Below sets the user_role and user_ask_role by asking a question.
  # You can set user_ask_role directly instead to either 'plaintiff' or 'defendant'
  user_ask_role
  % else:
  user_role = "${ interview.typical_role }"
  user_ask_role = "${ interview.typical_role }"
  % endif
  % for field in interview.questions.interview_order_list(interview.all_fields, screen_reordered):
  ${ field }
  % endfor
  % if not generate_download_screen:
  saved_report_data
  % endif
  interview_order_${ interview.interview_label } = True
---
###################### Main order ######################
comment: |
  This block includes the logic for standalone interviews.
  Delete mandatory: True to include in another interview
mandatory: True
code: |
  al_intro_screen
  ${ interview.interview_label }_intro
  interview_order_${ interview.interview_label }
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
  % if len(interview.all_fields.signatures()) > 0:
  ${ interview.interview_label }_preview_question
  basic_questions_signature_flow    
  % for signature_field in interview.all_fields.signatures():
  ${ signature_field.trigger_gather(interview.all_fields.custom_people_plurals) }
  % endfor
  % endif
  ${ interview.interview_label }_download
  % else:
  ${ interview.interview_label }_thank_you
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
continue button field: ${ interview.interview_label }_intro
question: |
  ${ interview.title }
subquestion: |
${ indent(interview.getting_started, 2) }
<%doc>
    Main question loop
</%doc>\
% for question in interview.questions:
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
id: preview ${ interview.interview_label }
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

  <%text>${</%text> action_button_html(url_action('review_${ interview.interview_label }'), label='Edit answers', color='info') <%text>}</%text>
  
  Remember to come back to this window to continue and sign your form.
continue button field: ${ interview.interview_label }_preview_question    
% endif
<%doc>
    TODO(qs): signature fields shouldn't depend on whether we have a download screen
</%doc>\
% if generate_download_screen:
---
code: |
  signature_fields = ${ str(list(interview.all_fields.built_in_signature_triggers()) + [field.trigger_gather(interview.all_fields.custom_people_plurals) for field in interview.all_fields.signatures()] ) }
% endif
% for custom_signature in interview.all_fields.custom_signatures():
---
question: |
  ${custom_signature.variable.replace("_", " ").capitalize()}, sign below
signature: ${ custom_signature }
% endfor
% for field in interview.all_fields.skip_fields():
---
code: |
  ${ field.variable } = DAEmpty()
% endfor
% for field in interview.all_fields.code_fields():
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
  [user.address.address for user in users.complete_elements()]
  addresses_to_search = [user.address for user in users.complete_elements()]
% endif
<%doc>
    Review screens

    TODO(qs): why use fix_id here?
</%doc>\
---
id: ${ fix_id(interview.interview_label) } review screen
event: review_${ interview.interview_label }
question: |
  Review your answers
review:
  % for coll in interview.all_fields.find_parent_collections():
${ review_yaml(coll) | trim }\
  % endfor
% for coll in interview.all_fields.find_parent_collections():
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
id: download ${ interview.interview_label }
event: ${ interview.interview_label }_download
question: |
  All done
subquestion: |
  Thank you <%text>${users}</%text>. Your form is ready to download and deliver.
  
  View, download and send your form below. Click the "Edit answers" button to fix any mistakes.

  <%text>${</%text> action_button_html(url_action('review_${ interview.interview_label }'), label='Edit answers', color='info') <%text>}</%text>
  
  <%text>
  ${ al_user_bundle.download_list_html() }
  </%text>

  <%text>${</%text> al_user_bundle.send_button_html(show_editable_checkbox=${False if any(map(lambda templ: templ.mimetype == "application/pdf", interview.uploaded_templates)) else True}) <%text>}</%text>

progress: 100
<%doc>
    Else, if no file output and just saving to database:
    generate a thank you page and code blocks for saving data to database
</%doc>\
% else:
---
id: thank you
event: ${ interview.interview_label }_thank_you
question: |
  Thank You!
subquestion: |
  Thank you for submitting your answers! We appreciate your time. 
  
  A copy of your answers was saved in our database.

progress: 100
---
variable name: input_fields_dict
data from code:
  % for field in interview.all_fields.elements:
  "${ field.get_settable_var() }": showifdef("${ field.get_settable_var() }")
  % endfor
---
code: |
  save_input_data(title = "${ interview.interview_label }", input_dict = input_fields_dict)
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
# ALDocument objects specify the metadata for each template
objects:
  % if interview.include_next_steps:
  - ${ interview.interview_label }_Post_interview_instructions: ALDocument.using(title="Instructions", filename="${ interview.interview_label }_next_steps.docx", enabled=True, has_addendum=False)
  % endif
  % if len(interview.uploaded_templates) == 1:
  - ${ interview.interview_label }_attachment: ALDocument.using(title="${ interview.title }", filename="${ interview.interview_label }", enabled=True, has_addendum=${ interview.all_fields.has_addendum_fields() }, ${ "default_overflow_message=AL_DEFAULT_OVERFLOW_MESSAGE" if interview.all_fields.has_addendum_fields() else ''})
  % else:
  % for document in interview.uploaded_templates:
  - ${ varname(base_name(document.filename)) }: ALDocument.using(title="${ base_name(document.filename).capitalize().replace("_", " ") }", filename="${ base_name(document.filename) }", enabled=True, has_addendum=${ interview.all_fields.has_addendum_fields() }, ${ "default_overflow_message=AL_DEFAULT_OVERFLOW_MESSAGE" if interview.all_fields.has_addendum_fields() else ''})
  % endfor
  % endif
---
# Bundles group the ALDocuments into separate downloads, such as for court and for the user
objects:
  % if interview.include_next_steps:
  - al_user_bundle: ALDocumentBundle.using(elements=[${ f"{ interview.interview_label }_Post_interview_instructions"}, ${ interview.attachment_varnames()}], filename="${interview.interview_label}", title="All forms to download for your records", enabled=True)
  % else:
  - al_user_bundle: ALDocumentBundle.using(elements=[${ interview.attachment_varnames()}], filename="${interview.interview_label}", title="All forms to download for your records", enabled=True)
  % endif
  % if interview.court_related:
  - al_court_bundle: ALDocumentBundle.using(elements=[${ interview.attachment_varnames() }],  filename="${interview.interview_label}", title="All forms to deliver to court", enabled=True)
  % else:
  - al_recipient_bundle: ALDocumentBundle.using(elements=[${ interview.attachment_varnames() }],  filename="${interview.interview_label}", title="All forms to file", enabled=True)
  % endif
---
# Each attachment defines a key in an ALDocument. We use `i` as the placeholder here so the same template is 
# used for "preview" and "final" keys, and logic in the template checks the value of 
# `i` to show or hide the user's signature
attachment:
  name: Post-interview-Instructions
  filename: ${ interview.interview_label }_next_steps
  docx template file: ${ interview.interview_label }_next_steps.docx
  variable name: ${ interview.interview_label }_Post_interview_instructions[i]
  skip undefined: True
  tagged pdf: True
% for document in interview.uploaded_templates:
---
attachment:
% if len(interview.uploaded_templates) == 1:
  name: ${ interview.interview_label.replace('_',' ') }
  filename: ${ interview.interview_label }
  variable name: ${ interview.interview_label }_attachment[i]
% else:
  name: ${ base_name(document.filename).replace('_',' ') }
  filename: ${ base_name(document.filename) }
  variable name: ${ varname(base_name(document.filename)) }[i]
% endif
% if document.mimetype == "application/pdf":
  skip undefined: True
  pdf template file: ${ document.filename }
  fields:
    % for field in interview.all_fields.matching_pdf_fields_from_file(document):
${ attachment_yaml(field, attachment_name=f"{ interview.interview_label}_attachment") }\
    % endfor
% else:
  skip undefined: True
  docx template file: ${ document.filename }
  tagged pdf: True
% endif
% endfor
% if interview.all_fields.has_addendum_fields():
---
code: |
  % for field in interview.all_fields.addendum_fields():
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
<%doc>
  HACK: add the name change questions directly to the Weaver output for now. See https://github.com/SuffolkLITLab/docassemble-AssemblyLine/pull/668#discussion_r1149774674
  We need a more generalized way to do this in the future but this can get us through LIT Con
</%doc>
% if showifdef("add_name_change_questions"):
---
id: consent of parent 1
question: |
  Do you consent to ${ children[0].preferred_name }'s name change?
fields:
  - I consent: users[0].consented_to_name_change
    datatype: yesnoradio
---
id: consent of parent 1
question: |
  Does ${ users[1] } consent to ${ children[0].preferred_name }'s name change?
fields:
  - ${ users[1] } consents: users[0].consented_to_name_change
    datatype: yesnoradio
---
id: consent of parent 1 attached
question: |
  Is your consent attached?
fields:
  - My consent is attached: users[0].parent_consent_attached
    datatype: yesnoradio
  - Why not?: users[0].no_consent_attached_explanation
    datatype: area
    rows: 2
    show if:
      variable: users[0].parent_consent_attached
      is: False
---
id: consent of parent 2 attached
question: |
  Is ${ users[1] }'s consent attached?
fields:
  - ${ users[1] }'s consent is attached: users[0].parent_consent_attached
    datatype: yesnoradio
  - Why not?: users[1].no_consent_attached_explanation
    datatype: area
    rows: 2
    show if:
      variable: users[1].parent_consent_attached
      is: False
% endif