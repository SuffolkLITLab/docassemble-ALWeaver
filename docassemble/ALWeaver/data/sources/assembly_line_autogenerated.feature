Feature: Generated docassemble test

Scenario: Generated scenario
  Given I start the interview at "assembly_line.yml"
  And I tap the "#build_from_scratch" element
  And the user gets to "download-your-interview" with this data:
    | var | value |
    | mixed_fields_checkup_status['interview.all_fields_present'] | True |
    | mixed_fields_checkup_status['no_unexpected_fields'] | False |
    | mixed_fields_checkup_status['correct_reserved_fields'] | False |
    | warn_no_recognized_al_labels | Sample answer |
    | fields_checkup_status['interview.all_fields_present'] | True |
    | fields_checkup_status['no_unexpected_fields'] | False |
    | fields_checkup_status['correct_reserved_fields'] | False |
    | will_handle_errors | Sample answer |
    | all_look_good['all_checkboxes_checked'] | True |
    | mako_syntax_in_docx | Sample answer |
    | warn_pdf_variable_names_in_docx | Sample answer |
    | warn_reserved_variables_in_docx | Sample answer |
    | docx_fields_checkup_status['interview.all_fields_present'] | True |
    | docx_fields_checkup_status['no_unexpected_fields'] | False |
    | docx_fields_checkup_status['correct_reserved_fields'] | False |
    | sharing_type | tell_friend |
    | how_to_share | email_or_sms |
    | share_form_from_name | Sample answer |
    | interview_type | regular |
    | interview.uploaded_templates | test_civil_docketing_statement.pdf |
    | interview.help_page_url | https://example.com/help |
    | interview.help_page_title | Sample answer |
    | interview.help_source_document | Sample answer |
    | yes_recognize_form_fields | Sample answer |
    | offer_auto_label_existing_fields | Sample answer |
    | interview.original_form | https://example.com/form |
    | interview.original_form_published_on | 01/02/2026 |
    | interview.categories | Sample answer |
    | interview.has_other_categories | True |
    | interview.other_categories | Sample answer |
    | interview.court_related | True |
    | interview.form_type | starts_case |
    | interview.allowed_courts | Sample answer |
    | interview.allowed_courts_text | Sample answer |
    | interview.author | % if user_logged_in():\n${ user_info().first_name } ${ user_info().last_name }\n% else:\nCourt Forms Online\n% endif\n |
    | interview.default_country_code | Sample answer |
    | interview.state | Sample answer |
    | interview.jurisdiction | Sample answer |
    | interview.jurisdiction_choices | Sample answer |
    | interview.org_choices | Sample answer |
    | interview.output_mako_choice | Default configuration:standard AssemblyLine\n |
    | interview.intro_prompt | Sample answer |
    | interview.title | Sample answer |
    | interview.short_title | Sample answer |
    | interview.customize_file_name | True |
    | interview_label_draft | Sample answer |
    | interview.form_number | Sample answer |
    | interview.filing_fee | 1 |
    | interview.description | Sample answer |
    | interview.can_I_use_this_form | Sample answer |
    | interview.getting_started | % if hasattr(interview, \"llm_draft_getting_started\"):\n${ interview.llm_draft_getting_started }\n% else:\nThis interview will help you ${ interview.intro_prompt[0:1].lower() }${ interview.intro_prompt[1:] }.\n\nBefore you get started, please gather:\n\n1. \n1. \n1. \n\nWhen you are finished, you will need to:\n\n1. \n1.\n% endif\n |
    | interview.when_you_are_finished | Sample answer |
    | interview.landing_page_url | https://example.com/landing |
    | interview.integrated_efiling | False |
    | interview.integrated_email_filing | False |
    | interview.efiling_enabled | False |
    | interview.requires_notarization | False |
    | interview.unlisted | False |
    | interview.footer | Sample answer |
    | interview.estimated_completion_minutes | 10 |
    | interview.estimated_completion_delta | 5 |
    | interview.include_next_steps | True |
    | interview.customize_next_steps | Sample answer |
    | interview.next_steps_document_title | answer |
    | interview.next_steps_document_concept | request |
    | interview.next_steps_help_organization | Sample answer |
    | interview.next_steps_help_url | https://example.com/next-steps |
    | interview.generate_next_steps_qr_code | Sample answer |
    | interview.custom_next_steps_instructions["what_happens_next"] | Sample answer |
    | interview.custom_next_steps_instructions["what_can_decision_maker_do"] | Sample answer |
    | interview.custom_next_steps_instructions["what_happens_if_i_win"] | Sample answer |
    | interview.typical_role | unknown |
    | interview.questions[0].is_informational_screen | True |
    | interview.questions[0].question_text | Screen ${nice_number(i+1)} |
    | interview.questions[0].subquestion_text | Sample answer |
    | interview.questions[0].field_list | Sample answer |
    | interview.all_fields[0].label | Sample answer |
    | interview.all_fields[0].variable | Sample answer |
    | interview.all_fields[0].field_type | Sample answer |
    | interview.all_fields[0].is_optional | True |
    | interview.all_fields[0].send_to_addendum | True |
    | interview.all_fields[0].code | Sample answer |
    | interview.all_fields[0].choices | Sample answer |
    | interview.questions[0].fld_order_list | Sample answer |
    | interview.questions[0].table_data | Sample answer |
    | interview.questions[0].edit_question | Sample answer |
    | interview.enable_navigation | False |
    | scr_order_list | Sample answer |
    | scr_table_data | Sample answer |
    | im_feeling_lucky | False |
    | interview.use_llm_assist | True |
    | not_authorized | Sample answer |
    | multi_user | True |
    | process_url_args | Sample answer |
    | process_im_feeling_lucky | Sample answer |
    | weaver_intro | Sample answer |
    | set_interview_type_vars | Sample answer |
    | set_name_of_current_session_from_filename | Sample answer |
    | process_field_recognition | Sample answer |
    | autolabel_existing_pdf_fields_task_done | Sample answer |
    | autolabel_target_document_type | pdf |
    | apply_autolabel_field_name_changes | Sample answer |
    | apply_autolabel_docx_label_changes | Sample answer |
    | process_field_normalization | Sample answer |
    | initial_get_fields | Sample answer |
    | validate_field_names | Sample answer |
    | fields_checkup_status | Sample answer |
    | all_look_good | Sample answer |
    | validate_docx | Sample answer |
    | validate_mixed_documents | Sample answer |
    | interview.all_fields.gathered | Sample answer |
    | normalize_all_fields_final_display_var | Sample answer |
    | process_llm_stepwise_prefill | Sample answer |
    | set_name_of_current_session | Sample answer |
    | process_people_variables | Sample answer |
    | ask_people_quantity_question | Sample answer |
    | preview_next_steps | Sample answer |
    | preview_final_next_steps | Sample answer |
    | choose_field_types | Sample answer |
    | no_template_default_values | Sample answer |
    | review_fields_after_labeling | Sample answer |
    | normalize_question_field_list | Sample answer |
    | review_weaver | Sample answer |
    | wrote_interview | Sample answer |
    | show_interview | Sample answer |
    | yes_normalize_fields | False |
    | interview.uploaded_templates.mimetype | application/pdf |
    | interview.help_source_text | Sample answer |
    | interview.autolabel_payload_loaded | False |
    | autolabel_target_document_index | -1 |
    | has_detected_fields_for_autolabel | False |
    | document.mimetype | application/pdf |
    | break | Sample answer |
    | autolabel_existing_pdf_fields_failed | Sample answer |
    | waiting_screen_autolabel_existing_pdf_fields | Sample answer |
    | item[0] | Sample answer |
    | autolabel_existing_pdf_fields_failed | True |
    | review_autolabel_docx_label_changes | True |
    | autolabel_docx_no_suggestions_found | True |
    | interview.questions.gathered | False |
    | interview.questions.there_are_any | False |
    | review_autolabel_field_name_changes | True |
    | autolabel_field_name_overrides[0] | Sample answer |
    | interview.short_filename | Sample answer |
    | interview.llm_draft_intro_prompt | Sample answer |
    | preview_next_steps | True |
    | preview_final_next_steps | True |
    | review_fields_after_labeling | True |
    | ask_people_quantity_question | True |
    | people_quantity_question | Sample answer |
    | choose_field_types | True |
    | field.field_type | code |
    | field.final_display_var | Sample answer |
    | errors[0] | parsing_exception |
    | jinja_exception | Sample answer |
    | exit_keywords_in_docx | Sample answer |
    | non_descriptive_field_name | ignore |
    | custom_only | False |
    | x.needs_continue_button_field | False |
    | interview.questions.field_list.gathered | True |
    | playground_publish_success | False |
    | playground_publish_error | Sample answer |
    | playground_project_name | Sample answer |
    | playground_interview_source | Sample answer |
    | playground_project_url | https://example.com/project |
    | interview.questions[0].type | question |
    | interview.all_fields[0].has_label | True |
    | interview.all_fields[0].source_document_type | docx |
    | added_other_party | False |
    | new_object.type | ALPeopleList |
    | people_quantities[0] | one |
    | objects.gathered | True |
    | interview.all_fields[0].edit_field | True |
    | interview.questions[0].edit_question | True |
    | interview_sections_defaults_loaded | True |
    | show_screen_order | True |
    | inflate_renamed_upload | True |
    | generate_download_screen | Sample answer |
    | package_version_number | playground |
    | github_repo_name | docassemble-ALWeaver |
    | run_package | Sample answer |
    | waiting_screen | Sample answer |
    | button_install_package | True |
    | waiting_screen_uninstall | Sample answer |
    | button_uninstall_package | True |
    | task_complete | completed |
    | task_succeeded | True |
    | screen_tbl_done | True |
    | interview.questions[0].edit_table | Sample answer |
    | interview.questions[0].field_tbl_done | True |
    | show_field_order | True |
    | have_template_to_load | False |
    | interview.lucky_base_initialized | True |
    | interview.lucky_lm_drafting_task_started | True |
    | interview.lucky_lm_drafting_payload_applied | True |
    | waiting_screen_lucky_drafting | Sample answer |
    | interview.all_fields.field_type | multiple choice radio |
    | review_fields_to_add_template | Sample answer |