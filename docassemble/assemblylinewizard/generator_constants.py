"""
Constants for interview_generator.py
"""

# This is to workaround fact you can't do local import in Docassemble playground
class Object(object):
  pass

generator_constants = Object()

# Words that are reserved exactly as they are
generator_constants.RESERVED_WHOLE_WORDS = [
  'signature_date',  # this is the plural version of this?
  #'attorney_of_record_address_on_one_line',
]

# Prefixes for singular person-like objects, like trial courts that
# should be left undefined to trigger their question
generator_constants.UNDEFINED_PERSON_PREFIXES = [
  "trial_court",
]

# Plural vars representing people
generator_constants.PEOPLE_VARS = [
  'users',
  'other_parties',
  'plaintiffs',
  'defendants',
  'petitioners',
  'respondents',
  'spouses',
  'parents',
  'guardians',
  'caregivers',
  'attorneys',
  'translators',
  'debt_collectors',
  'creditors',
  'children',
  'guardians_ad_litem',
  'witnesses',
  'decedents',
  'interested_parties',
]  

# Part of handling plural labels
generator_constants.RESERVED_VAR_PLURALS = generator_constants.PEOPLE_VARS + [
  'courts',
  'docket_numbers',
]

# Prefixes as they would appear in a PDF (singular)
generator_constants.RESERVED_PREFIXES = ["user",
  "other_party",
  "child",
  "plaintiff",
  "defendant",
  "petitioner",
  "respondent",
  "spouse",
  "parent",
  "caregiver",
  "attorney",
  "translator",
  "debt_collector",
  "creditor",
  "witness",
  "court",
  "docket_number",
  "signature_date",
  # Can't find a way to make order not matter here
  # without making everything in general more messy
  "guardian_ad_litem",
  "guardian",
  "decedent",
  "interested_party",
  "trial_court",
  ]

# reserved_pluralizers_map

generator_constants.RESERVED_PERSON_PLURALIZERS_MAP = {
  'user': 'users',
  'plaintiff': 'plaintiffs',
  'defendant': 'defendants',
  'petitioner': 'petitioners',
  'respondent': 'respondents',
  'spouse': 'spouses',
  'parent': 'parents',
  'guardian': 'guardians',
  'caregiver': 'caregivers',
  'attorney': 'attorneys',
  'translator': 'translators',
  'debt_collector': 'debt_collectors',
  'creditor': 'creditors',
  # Non-s plurals
  'other_party': 'other_parties',
  'child': 'children',
  'guardian_ad_litem': 'guardians_ad_litem',
  'witness': 'witnesses',
  'decedent': 'decedents',
  'interested_party': 'interested_parties',
}

generator_constants.RESERVED_PLURALIZERS_MAP = {** generator_constants.RESERVED_PERSON_PLURALIZERS_MAP, **{
  'court': 'courts',
  'docket_number': 'docket_numbers',
}}

# Any reason to not make all suffixes available to everyone?
# Yes: it can break variables that overlap but have a different meaning
# Better to be explicit

# Some common attributes that can be a clue it's a person object
generator_constants.PEOPLE_SUFFIXES_MAP = {
  '_name': "",  # full name
  '_name_full': "",  # full name
  '_name_first': ".name.first",
  '_name_middle': ".name.middle",
  '_name_middle_initial': ".name.middle_initial()",
  '_name_last': ".name.last",
  '_name_suffix': ".name.suffix",
  '_gender': ".gender",
  # '_gender_male': ".gender == 'male'",
  # '_gender_female': ".gender == 'female'",
  '_birthdate': ".birthdate.format()",
  '_age': ".age_in_years()",
  '_email': ".email",
  '_phone': ".phone_number",
  '_phone_number': ".phone_number",
  '_mobile': ".mobile_number",
  '_mobile_number': ".mobile_number",
  '_phones': ".phone_numbers()",
  '_address_block': ".address.block()",
  # TODO: deprecate street and street2 from existing forms and documentation
  '_address_street': ".address.address",
  '_address_street2': ".address.unit",
  '_address_address': ".address.address",
  '_address_unit': ".address.unit",
  '_address_city': ".address.city",
  '_address_state': ".address.state",
  '_address_zip': ".address.zip",
  '_address_county': ".address.county",
  '_address_country': ".address.country",
  '_address_on_one_line': ".address.on_one_line()",
  '_address_line_one': ".address.line_one()",
  '_address_city_state_zip': ".address.line_two()",
  '_signature': ".signature",
  '_mail_address_block': ".mail_address.block()",
  '_mail_address_street': ".mail_address.address",
  '_mail_address_street2': ".mail_address.unit",
  '_mail_address_address': ".mail_address.address",
  '_mail_address_unit': ".mail_address.unit",
  '_mail_address_city': ".mail_address.city",
  '_mail_address_state': ".mail_address.state",
  '_mail_address_zip': ".mail_address.zip",
  '_mail_address_county': ".mail_address.county",
  '_mail_address_country': ".mail_address.country",
  '_mail_address_on_one_line': ".mail_address.on_one_line()",
  '_mail_address_line_one': ".mail_address.line_one()",
  '_mail_address_city_state_zip': ".mail_address.line_two()",
  '_mail_address': ".mail_address",
}

generator_constants.PEOPLE_SUFFIXES = list(generator_constants.PEOPLE_SUFFIXES_MAP.values()) + ['.name.full()','.name']

# reserved_suffixes_map
generator_constants.RESERVED_SUFFIXES_MAP = {**generator_constants.PEOPLE_SUFFIXES_MAP, **{
  # Court-specific
  # '_name_short': not implemented,
  '_division': ".division",
  '_county': ".address.county",
  '_department': ".department",
}}

# these might be used in a docx, but we don't transform PDF fields to use these
# suffixes
generator_constants.DOCX_ONLY_SUFFIXES = [
    r'\.birthdate',
    r'\.birthdate.format\(.*\)',
    r'\.familiar\(\)',
    r'\.familiar_or\(\)',
    r'\.phone_numbers\(\)',
    r'\.formatted_age\(\)'
]

generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX = {
  '\.address.block\(\)$': '.address.address',
  '\.address.line_one\(\)$': '.address.address',
  '\.address.line_two\(\)$': '.address.address',
  '\.address.on_one_line\(\)$': '.address.address',
  '\.age_in_years\(\)$': '.birthdate',
  '\.birthdate.format\(.*\)$': '.birthdate',
  '\.familiar_or\(\)$': '.name.first',
  '\.familiar\(\)$': '.name.first',
  '\.formatted_age\(.*\)$': '.birthdate',
  '\.mail_address.block\(\)$': '.mail_address.address',
  '\.mail_address.line_one\(\)$': '.mail_address.address',
  '\.mail_address.line_two\(\)$': '.mail_address.address',
  '\.mail_address.on_one_line\(\)$': '.mail_address.address',
  '\.name.middle_initial\(\)$': '.name.first',
  '\.phone_numbers\(\)$': '.phone_number',
}

# Test needed: Jinja `{{ parents[0].name_of_dog }}` should remain the same,
# not `.name.full()` in the review screen displayed value
generator_constants.FULL_DISPLAY = {
  '\.name$': '.name.full()',
  '\.address$': '.address.block()',
  '\.mail_address$': '.mail_address.block()'
}

# Possible values for 'Allowed Courts', when looking up courts to submit to
generator_constants.COURT_CHOICES = [
  'Boston Municipal Court',
  'District Court',
  'Superior Court',
  'Housing Court',
  'Probate and Family Court',
  'Juvenile Court',
  'Land Court'
]