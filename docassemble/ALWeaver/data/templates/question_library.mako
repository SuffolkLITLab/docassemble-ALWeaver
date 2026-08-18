<%doc>

    Copies of AssemblyLine's baseline questions, specialized for one object.

    Most of the questions in docassemble.AssemblyLine's `ql_baseline.yml` are
    `generic object:` questions: a single block that serves `users`, `children`,
    `witnesses` and every other list of people. That is why you cannot copy one out
    of `ql_baseline.yml` and edit it -- you would first have to delete the
    `generic object:` line and rewrite every `x` into the name of your own object.

    When the author leaves "Copy the AssemblyLine questions about people into my
    interview" turned on, the Weaver writes these blocks into the generated YAML
    instead, already pointed at the objects the interview declares. They behave like
    the AssemblyLine originals until somebody edits them, and because they live in
    the generated file they take precedence over the AssemblyLine versions.

    Which blocks get written is decided in `question_library.py`; the wording lives
    here. Keep this file in sync with `ql_baseline.yml` when the baseline questions
    change -- each def below names the `ql_baseline.yml` block it came from.

    Writing questions in here: `${ ... }` and a leading `%` belong to *this*
    template and are resolved while the interview is generated. To put a Mako
    expression into the generated interview, write `<%text>${</%text> ... }`, and
    for a Mako control line write `<%text>%</%text> if ...`.

</%doc>\
<%def name="baseline_question_yaml(entry)">\
<%
    kind = entry["kind"]
    var = entry["var"]
    singular = entry["singular"]
    plural = entry["plural"]
    # Person questions are asked once per list item, so they are written against
    # `users[i]` rather than `users`. A standalone ALIndividual has no index.
    item = "%s[i]" % var if entry["is_list"] else var
%>\
% if kind == "there_are_any":
${ baseline_there_are_any(var, plural) }\
% elif kind == "how_many":
${ baseline_how_many(var, plural) }\
% elif kind == "names":
${ baseline_names(var, singular, plural) }\
% elif kind == "there_is_another":
${ baseline_there_is_another(var, singular) }\
% elif kind == "name":
${ baseline_name(var) }\
% elif kind == "address":
${ baseline_address(var, item, singular) }\
% elif kind == "mailing_address":
${ baseline_mailing_address(item, singular) }\
% elif kind == "birthdate":
${ baseline_birthdate(item, singular) }\
% elif kind == "gender":
${ baseline_gender(item, singular) }\
% elif kind == "pronouns":
${ baseline_pronouns(var, item, singular) }\
% elif kind == "language":
${ baseline_language(var, item, singular) }\
% elif kind == "phone_number":
${ baseline_phone(item, singular, "phone_number", "phone number", "Phone") }\
% elif kind == "mobile_number":
${ baseline_phone(item, singular, "mobile_number", "mobile number", "Mobile number") }\
% elif kind == "email":
${ baseline_email(item, singular) }\
% endif
</%def>\
<%doc>
    From `ql_baseline.yml`, id: who will be on this form -- except for
    `other_parties`, which AssemblyLine asks about in
    id: is there an opposing party?
</%doc>\
<%def name="baseline_there_are_any(var, plural)">\
---
id: ${ fix_id("any " + plural) }
question: |
% if var == "other_parties":
  <%text>%</%text> if al_form_type in ['starts_case', 'existing_case', 'appeal'] and user_started_case:
  Is there a **defendant** or respondent in this case?
  <%text>%</%text> elif al_form_type in ['starts_case', 'existing_case', 'appeal']:
  Is there a **plaintiff** or petitioner in this case?
  <%text>%</%text> else:
  Is there someone on the other side of your dispute?
  <%text>%</%text> endif
subquestion: |
  <%text>%</%text> if al_form_type in ['starts_case', 'existing_case', 'appeal'] and user_started_case:
  Answer yes if there is a person or organization you are suing or taking to court.
  <%text>%</%text> elif al_form_type in ['starts_case', 'existing_case', 'appeal']:
  You should be able to find out from the paperwork that told you to go to court.

  Answer yes if someone else has sued you or is bringing you to court.
  <%text>%</%text> endif
% else:
  Will this form include any ${ plural }?
% endif
fields:
  - no label: ${ var }.there_are_any
    datatype: yesnoradio
</%def>\
<%doc>
    From `ql_baseline.yml`, id: how many witnesses
</%doc>\
<%def name="baseline_how_many(var, plural)">\
---
id: ${ fix_id("how many " + plural) }
question: |
  Are there any ${ plural }?
fields:
  - "Any ${ plural }?": ${ var }.there_are_any
    datatype: yesnoradio
  - "How many <span class='visually-hidden'>${ plural }</span>?": ${ var }.target_number
    datatype: integer
    show if: ${ var }.there_are_any
validation code: |
  if not ${ var }.there_are_any:
    ${ var }.target_number = 0
</%def>\
<%doc>
    From `ql_baseline.yml`, id: names of people -- except for `users` and
    `other_parties`, which AssemblyLine asks about in id: other users names and
    id: names of opposing parties
</%doc>\
<%def name="baseline_names(var, singular, plural)">\
---
id: ${ fix_id(plural + " names") }
sets:
  - ${ var }[i].name.first
  - ${ var }[i].name.last
  - ${ var }[i].name.middle
  - ${ var }[i].name.suffix
question: |
% if var == "users":
  <%text>%</%text> if i == 0 and al_person_answering == "user":
  What is your name?
  <%text>%</%text> elif al_form_type in ['starts_case', 'existing_case', 'appeal']:
  Who is the <%text>${ ordinal(i) }</%text> person on your side of the case?
  <%text>%</%text> else:
  What is the name of the <%text>${ ordinal(i) }</%text> person who is adding their
  name to this form with you?
  <%text>%</%text> endif
% elif var == "other_parties":
  <%text>%</%text> if user_started_case:
  Name of <%text>${ ordinal(i) }</%text> **defendant** or respondent in this matter
  <%text>%</%text> else:
  Name of <%text>${ ordinal(i) }</%text> **plaintiff** or petitioner in this matter
  <%text>%</%text> endif
% else:
  <%text>%</%text> if hasattr(${ var }, 'ask_number') and ${ var }.ask_number and ${ var }.target_number == 1:
  Name of ${ singular }
  <%text>%</%text> else:
  Name of the <%text>${ ordinal(i) }</%text> ${ singular }
  <%text>%</%text> endif
% endif
fields:
  - code: |
% if var == "other_parties":
      other_parties[i].name_fields(person_or_business="unsure")
% else:
      ${ var }[i].name_fields()
% endif
</%def>\
<%doc>
    From `ql_baseline.yml`, id: any other people -- except for `users` and
    `other_parties`, which AssemblyLine asks about in id: any other users and
    id: any other opposing parties
</%doc>\
<%def name="baseline_there_is_another(var, singular)">\
---
id: ${ fix_id("another " + singular) }
question: |
% if var == "users":
  <%text>%</%text> if al_form_type in ['starts_case', 'existing_case', 'appeal']:
  Is anyone else on your side of this case?
  <%text>%</%text> else:
  Is anyone else adding their name to this form with you?
  <%text>%</%text> endif
subquestion: |
  <%text>%</%text> if len(users.elements) > 1:
  So far you have told us about <%text>${</%text> comma_and_list(users.complete_elements()) }.
  <%text>%</%text> endif
% elif var == "other_parties":
  <%text>%</%text> if user_started_case:
  Is there any other **defendant** or respondent in this matter?
  <%text>%</%text> else:
  Is there any other **plaintiff** or petitioner in this matter?
  <%text>%</%text> endif
% else:
  Is there another ${ singular } to tell us about?
% endif
fields:
  - no label: ${ var }.there_is_another
    datatype: yesnoradio
</%def>\
<%doc>
    From `ql_baseline.yml`, id: name of ALIndividual. Used for a standalone
    ALIndividual rather than a list of people.
</%doc>\
<%def name="baseline_name(var)">\
---
id: ${ fix_id(var + " name") }
sets:
  - ${ var }.name.first
  - ${ var }.name.last
  - ${ var }.name.middle
  - ${ var }.name.suffix
question: |
  What is <%text>${</%text> ${ var }.object_possessive('name') }?
fields:
  - code: |
      ${ var }.name_fields()
</%def>\
<%doc>
    From `ql_baseline.yml`, id: persons address -- except for `users`, which
    AssemblyLine asks about in id: user i's address, where later users can reuse
    the first user's address.
</%doc>\
<%def name="baseline_address(var, item, singular)">\
---
id: ${ fix_id(singular + " address") }
sets:
  - ${ item }.address.address
  - ${ item }.address.city
  - ${ item }.address.state
  - ${ item }.address.zip
  - ${ item }.address.unit
  - ${ item }.address.country
question: |
% if var == "users":
  <%text>%</%text> if i == 0 and al_person_answering == "user":
  What is your address?
  <%text>%</%text> else:
  What is <%text>${ users[i] }</%text>'s address?
  <%text>%</%text> endif
fields:
  - label: |
      <%text>%</%text> if i > 0 and al_person_answering == "user":
      Same as your address
      <%text>%</%text> else:
      Same as <%text>${ users[0] }</%text>'s address
      <%text>%</%text> endif
    field: users[i].address
    datatype: object_radio
    choices:
      - users[0].address if defined("users[0].address.address") else None
    object labeler: |
      lambda y: y.on_one_line()
    none of the above: |
      Somewhere else
    disable others: True
    show if:
      code: |
        i > 0 and defined("users[0].address.address")
  - code: |
      users[i].address_fields(
          country_code=AL_DEFAULT_COUNTRY, default_state=AL_DEFAULT_STATE
      )
% else:
  What is <%text>${</%text> ${ item }.possessive('address') }?
fields:
  - code: |
      ${ item }.address_fields(
          country_code=AL_DEFAULT_COUNTRY, default_state=AL_DEFAULT_STATE
      )
% endif
</%def>\
<%doc>
    From `ql_baseline.yml`, id: any mailing address
</%doc>\
<%def name="baseline_mailing_address(item, singular)">\
---
id: ${ fix_id(singular + " mailing address") }
sets:
  - ${ item }.mailing_address.address
  - ${ item }.mailing_address.city
  - ${ item }.mailing_address.state
  - ${ item }.mailing_address.zip
  - ${ item }.mailing_address.unit
  - ${ item }.mailing_address.country
question: |
  What is <%text>${</%text> ${ item } }'s mailing address?
fields:
  - "<%text>${</%text> ${ item } }'s mailing address is": ${ item }.mailing_address
    datatype: object_radio
    choices:
      - ${ item }.address
    object labeler: |
      lambda y: y.on_one_line()
    none of the above: |
      Somewhere else
    disable others: True
  - code: |
      ${ item }.mailing_address.address_fields(
          country_code=AL_DEFAULT_COUNTRY, default_state=AL_DEFAULT_STATE
      )
</%def>\
<%doc>
    From `ql_baseline.yml`, id: birthdate question
</%doc>\
<%def name="baseline_birthdate(item, singular)">\
---
id: ${ fix_id(singular + " birthdate") }
question: |
  When was <%text>${</%text> ${ item } } born?
fields:
  - Birthdate: ${ item }.birthdate
    datatype: BirthDate
    alMonthLabel: <%text>${ word('Month') }</%text>
    alDayLabel: <%text>${ word('Day') }</%text>
    alYearLabel: <%text>${ word('Year') }</%text>
</%def>\
<%doc>
    From `ql_baseline.yml`, id: gender
</%doc>\
<%def name="baseline_gender(item, singular)">\
---
id: ${ fix_id(singular + " gender") }
sets:
  - ${ item }.gender
question: |
  What is <%text>${</%text> ${ item }.possessive('gender') }?
fields:
  - code: |
      ${ item }.gender_fields(show_help=True)
</%def>\
<%doc>
    From `ql_baseline.yml`, id: x's pronouns -- except for `users`, which
    AssemblyLine asks about in id: your pronouns
</%doc>\
<%def name="baseline_pronouns(var, item, singular)">\
---
id: ${ fix_id(singular + " pronouns") }
sets:
  - ${ item }.pronouns
question: |
% if var == "users":
  <%text>%</%text> if i == 0 and al_person_answering == "user":
  What are your pronouns?
  <%text>%</%text> else:
  What are <%text>${ users[i] }</%text>'s pronouns?
  <%text>%</%text> endif
% else:
  What are <%text>${</%text> ${ item } }'s pronouns?
% endif
fields:
  - code: |
      ${ item }.pronoun_fields(show_help=True, required=False)
</%def>\
<%doc>
    From `ql_baseline.yml`, id: language of individual -- except for `users`,
    which AssemblyLine asks about in id: language of user
</%doc>\
<%def name="baseline_language(var, item, singular)">\
---
id: ${ fix_id(singular + " language") }
sets:
  - ${ item }.language
question: |
% if var == "users":
  <%text>%</%text> if i == 0 and al_person_answering == "user":
  What language do you speak?
  <%text>%</%text> else:
  What language does <%text>${ users[i] }</%text> speak?
  <%text>%</%text> endif
% else:
  What language does <%text>${</%text> ${ item } } speak?
% endif
fields:
  - code: |
      ${ item }.language_fields(choices=al_language_user_choices)
</%def>\
<%doc>
    From `ql_baseline.yml`, id: persons phone number and id: persons mobile number
</%doc>\
<%def name="baseline_phone(item, singular, attribute, description, label)">\
---
id: ${ fix_id(singular + " " + description) }
question: |
  What is <%text>${</%text> ${ item } }'s ${ description }?
fields:
  - ${ label }: ${ item }.${ attribute }
    datatype: al_international_phone
</%def>\
<%doc>
    From `ql_baseline.yml`, id: email
</%doc>\
<%def name="baseline_email(item, singular)">\
---
id: ${ fix_id(singular + " email") }
question: |
  What is <%text>${</%text> ${ item } }'s email address?
fields:
  - Email: ${ item }.email
    datatype: email
</%def>\
