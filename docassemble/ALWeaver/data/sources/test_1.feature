Feature: Ensure the Weaver can run through to the end

Notes:
- Can't compare YML till ALKiln #479 is approved, merged, and published
- Have to double up on some rows until ALKiln #467 is approved, merged, and
  published to test questions loop and informational screen

@weaver1 @weaver
Scenario: I weave the civil docketing statement
  Given the max seconds for each Step is 90
  And I start the interview at "assembly_line.yml"
  Then I tap the "#upload" element and wait 5 seconds
  And I get to the question id "download-your-interview" with this data:
    | var | value | trigger |
    | interview_type | regular | |
    | im_feeling_lucky | False | |
    | install_en_core_web_lg| False | |
    | interview.uploaded_templates | test_civil_docketing_statement.pdf |  |
    | all_look_good['all_checkboxes_checked'] | True |  |
    | all_look_good['no_unusual_size_text'] | True |  |
    | all_look_good['signature_filled_in'] | True |  |
    | ask_people_quantity_question | True |  |
    | choose_field_types | True |  |
    | interview.all_fields[10].send_to_addendum | True |  |
    | interview.all_fields[27].send_to_addendum | True |  |
    | fields_checkup_status['interview.all_fields_present'] | True |  |
    | fields_checkup_status['correct_reserved_fields'] | True |  |
    | fields_checkup_status['no_unexpected_fields'] | True |  |
    | interview.author | Very cool author |  |
    | interview.categories['HO-00-00-00-00'] | True |  |
    | interview.court_related | True |  |
    | interview.default_country_code | US |  |
    | interview.form_type | starts_case |  |
    | interview.jurisdiction_choices['docassemble.ALAnyState:any_state.yml'] | False |  |
    | interview.jurisdiction_choices['docassemble.ALMassachusetts:al_massachusetts.yml'] | True |  |
    | interview.org_choices['docassemble.ALLouisianaSC:custom_organization.yml'] | False |  |
    | interview.org_choices['docassemble.ILAO:ilao-interview-framework.yml'] | False |  |
    | interview.org_choices['docassemble.MassAccess:massaccess.yml'] | True |  |
    | interview.original_form | http://an-online-form.com |  |
    | interview.state | MA |  |
    | interview_label_draft | test_civil_docketing_statement |  |
    | people_quantities['decision_maker'] | any |  |
    | people_quantities['users'] | more |  |
    | people_variables['decision_maker'] | True |  |
    | people_variables['have_served_other_party'] | False |  |
    | interview.customize_next_steps | False | |
    | preview_final_next_steps | True | |
    | interview.questions[i].field_list['interview.all_fields[0]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[10]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[11]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[12]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[13]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[14]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[15]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[16]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[17]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[18]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[19]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[1]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[20]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[21]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[22]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[23]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[24]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[25]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[26]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[27]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[28]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[29]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[2]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[2]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[30]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[31]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[32]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[33]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[34]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[3]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[4]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[5]'] | True | interview.questions[0].question_text |
    | interview.questions[i].field_list['interview.all_fields[6]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[7]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[8]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[9]'] | True | interview.questions[2].question_text |
    | interview.questions[i].field_list['interview.all_fields[35]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[36]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[37]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[38]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[39]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[40]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[41]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[41]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[42]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[43]'] | True | interview.questions[3].question_text |
    | interview.questions[i].field_list['interview.all_fields[44]'] | True | interview.questions[3].question_text |
    | interview.questions[i].has_mandatory_field | True | interview.questions[2].question_text |
    | interview.questions[i].question_text | Screen 1 custom title | interview.questions[0].question_text |
    | interview.questions[i].question_text | Screen 3 custom title | interview.questions[2].question_text |
    | interview.questions[i].question_text | Screen 4 custom title | interview.questions[3].question_text |
    | interview.questions[i].subquestion_text | Screen 1 text | interview.questions[0].question_text |
    | interview.questions[i].subquestion_text | Screen 3 body | interview.questions[2].question_text |
    | interview.questions[i].subquestion_text | Screen 4 body text | interview.questions[3].question_text |
    | interview.questions[i].is_informational_screen | True | interview.questions[1].question_text |
    | interview.questions[i].question_text | Screen 2 (informational) title | interview.questions[1].question_text |
    | interview.questions[i].subquestion_text | Screen 2 informational only | interview.questions[1].question_text |
    | review_fields_after_labeling | True |  |
    | show_screen_order | True |  |
    | weaver_intro | True |  |

@weaver2 @weaver @people_vars
Scenario: I weave the civil docketing statement
  Given the max seconds for each Step is 90
  And I start the interview at "assembly_line.yml"
  Then I tap the "#upload" element and wait 5 seconds
  And I get to the question id "how many people in interview" with this data:
    | var | value | trigger |
    | interview_type | regular | |
    | im_feeling_lucky | False | |
    | install_en_core_web_lg| False | |
    | interview.uploaded_templates | test_civil_docketing_statement.pdf |  |
    | all_look_good['all_checkboxes_checked'] | True |  |
    | all_look_good['no_unusual_size_text'] | True |  |
    | all_look_good['signature_filled_in'] | True |  |
    | ask_people_quantity_question | True |  |
    | choose_field_types | True |  |
    | interview.all_fields[10].send_to_addendum | True |  |
    | interview.all_fields[27].send_to_addendum | True |  |
    | fields_checkup_status['interview.all_fields_present'] | True |  |
    | fields_checkup_status['correct_reserved_fields'] | True |  |
    | fields_checkup_status['no_unexpected_fields'] | True |  |
    | interview.author | Very cool author |  |
    | interview.categories['HO-00-00-00-00'] | True |  |
    | interview.court_related | True |  |
    | interview.default_country_code | US |  |
    | interview.form_type | starts_case |  |
    | interview.jurisdiction_choices['docassemble.ALAnyState:any_state.yml'] | False |  |
    | interview.jurisdiction_choices['docassemble.ALMassachusetts:al_massachusetts.yml'] | True |  |
    | interview.org_choices['docassemble.ALLouisianaSC:custom_organization.yml'] | False |  |
    | interview.org_choices['docassemble.ILAO:ilao-interview-framework.yml'] | False |  |
    | interview.org_choices['docassemble.MassAccess:massaccess.yml'] | True |  |
    | interview.original_form | http://an-online-form.com |  |
    | interview.state | MA |  |
    | interview_label_draft | test_civil_docketing_statement |  |
  And I should not see the phrase "is the user of the form typically the Plaintiff"


@weaver3 @weaver @auto_drafting_mode
Scenario: I weave the civil docketing statement
  Given the max seconds for each Step is 90
  And I start the interview at "assembly_line.yml"
  Then I tap the "#upload" element and wait 5 seconds
  And I get to the question id "download-your-interview" with this data:
    | var | value | trigger |
    | interview_type | regular | |
    | im_feeling_lucky | True | |
    | interview.uploaded_templates | test_civil_docketing_statement.pdf |  |
    | show_screen_order | True |  |
