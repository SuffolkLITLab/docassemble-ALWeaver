Feature: Not sure of the purpose yet

Notes:
- Can't compare YML till ALKiln #479 is approved, merged, and published
- Have to double up on some rows until ALKiln #467 is approved, merged, and
  published to test questions loop and informational screen

Scenario: I weave the civil docketing statement
  Given I start the interview at "assembly_line.yml"
  And the max seconds for each Step is 90
  And I get to the question id "download-your-interview" with this data:
    | var | value | trigger |
    | all_look_good['all_checkboxes_checked'] | True |  |
    | all_look_good['no_unusual_size_text'] | True |  |
    | all_look_good['signature_filled_in'] | True |  |
    | ask_people_quantity_question | True |  |
    | choose_field_types | True |  |
    | fields[10].send_to_addendum | True |  |
    | fields[27].send_to_addendum | True |  |
    | fields_checkup_status['all_fields_present'] | True |  |
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
    | interview.typical_role | plaintiff |  |
    | interview_label_draft | test_civil_docketing_statement |  |
    | people_quantities['decision_maker'] | any |  |
    | people_quantities['users'] | more |  |
    | people_variables['decision_maker'] | True |  |
    | people_variables['have_served_other_party'] | False |  |
    | questions[i].field_list['fields[0]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[0]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[10]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[10]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[11]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[11]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[12]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[12]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[13]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[13]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[14]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[14]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[15]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[15]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[16]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[16]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[17]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[17]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[18]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[18]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[19]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[19]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[1]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[1]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[20]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[20]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[21]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[21]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[22]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[22]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[23]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[23]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[24]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[24]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[25]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[25]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[26]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[26]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[27]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[27]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[28]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[28]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[29]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[29]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[2]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[2]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[30]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[30]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[31]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[31]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[32]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[32]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[33]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[33]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[34]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[34]'] | True | questions[3].question_text |
    | questions[i].field_list['fields[3]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[3]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[4]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[4]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[5]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[5]'] | True | questions[0].question_text |
    | questions[i].field_list['fields[6]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[6]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[7]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[7]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[8]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[8]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[9]'] | True | questions[2].question_text |
    | questions[i].field_list['fields[9]'] | True | questions[2].question_text |
    | questions[i].has_mandatory_field | True | questions[2].question_text |
    | questions[i].has_mandatory_field | True | questions[2].question_text |
    | questions[i].question_text | Screen 1 custom title | questions[0].question_text |
    | questions[i].question_text | Screen 1 custom title | questions[0].question_text |
    | questions[i].question_text | Screen 3 custom title | questions[2].question_text |
    | questions[i].question_text | Screen 3 custom title | questions[2].question_text |
    | questions[i].question_text | Screen 4 custom title | questions[3].question_text |
    | questions[i].question_text | Screen 4 custom title | questions[3].question_text |
    | questions[i].subquestion_text | Screen 1 text | questions[0].question_text |
    | questions[i].subquestion_text | Screen 1 text | questions[0].question_text |
    | questions[i].subquestion_text | Screen 3 body | questions[2].question_text |
    | questions[i].subquestion_text | Screen 3 body | questions[2].question_text |
    | questions[i].subquestion_text | Screen 4 body text | questions[3].question_text |
    | questions[i].subquestion_text | Screen 4 body text | questions[3].question_text |
    | questions[i].is_informational_screen | True | questions[1].question_text |
    | questions[i].is_informational_screen | True | questions[1].question_text |
    | questions[i].question_text | Screen 2 (informational) title | questions[1].question_text |
    | questions[i].question_text | Screen 2 (informational) title | questions[1].question_text |
    | questions[i].subquestion_text | Screen 2 informational only | questions[1].question_text |
    | questions[i].subquestion_text | Screen 2 informational only | questions[1].question_text |
    | review_fields_after_labeling | True |  |
    | show_screen_order | True |  |
    | template_upload | test_civil_docketing_statement.pdf |  |
    | weaver_intro | True |  |
