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
  'attorney_of_record_address_on_one_line', 
]

# Vars representing people
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

generator_constants.RESERVED_PREFIXES = (r"^(user"  # deprecated, but still supported
  + r"|other_party"  # deprecated, but still supported
  + r"|child"
  + r"|plaintiff"
  + r"|defendant"
  + r"|petitioner"
  + r"|respondent"
  + r"|spouse"
  + r"|parent"
  + r"|caregiver"
  + r"|attorney"
  + r"|translator"
  + r"|debt_collector"
  + r"|creditor"
  + r"|witness"
  + r"|court"
  + r"|docket_number"
  + r"|signature_date"
  # Can't find a way to make order not matter here
  # without making everything in general more messy
  + r"|guardian_ad_litem"
  + r"|guardian"
  + r"|decedent"
  + r"|interested_party"
  + r")")

# reserved_pluralizers_map

generator_constants.RESERVED_PLURALIZERS_MAP = {
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
  'court': 'courts',
  'docket_number': 'docket_numbers',
  # Non-s plurals
  'other_party': 'other_parties',
  'child': 'children',
  'guardian_ad_litem': 'guardians_ad_litem',
  'witness': 'witnesses',
  'decedent': 'decedents',
  'interested_party': 'interested_parties',
}

# Any reason to not make all suffixes available to everyone?
# Yes: it can break variables that overlap but have a different meaning
# Better to be explicit

# Some common attributes that can be a clue it's a person object
generator_constants.PEOPLE_SUFFIXES_MAP = {
  '_name': "",  # full name
  '_name_full': "",  # full name
  '_name_first': ".name.first",
  '_name_middle': ".name.middle",
  '_name_last': ".name.last",
  '_name_suffix': ".name.suffix",
  '_gender': ".gender",
  # '_gender_male': ".gender == 'male'",
  # '_gender_female': ".gender == 'female'",
  '_birthdate': ".birthdate.format()",
  '_age': ".age_in_years()",
  '_email': ".email",
  '_phone': ".phone_number",
  '_address_block': ".address.block()",
  '_address_street': ".address.address",
  '_address_street2': ".address.unit",
  '_address_city': ".address.city",
  '_address_state': ".address.state",
  '_address_zip': ".address.zip",
  '_address_county': ".address.county",
  '_address_country': ".address.country",
  '_address_on_one_line': ".address.on_one_line()",
  '_address_line_one': ".address.line_one()",
  '_address_city_state_zip': ".address.line_two()",
  '_signature': ".signature",
}

generator_constants.PEOPLE_SUFFIXES = list(generator_constants.PEOPLE_SUFFIXES_MAP.values()) + ['.name.full()','.name']

# reserved_suffixes_map
generator_constants.RESERVED_SUFFIXES_MAP = {**generator_constants.PEOPLE_SUFFIXES_MAP, **{
  # Court-specific
  # '_name_short': not implemented,
  '_division': ".division",
  '_county': ".address.county",
}}

# these might be used in a docx, but we don't transform PDF fields to use these
# suffixes
generator_constants.DOCX_ONLY_SUFFIXES = [
    r'.birthdate',
    r'.birthdate.format\(.*\)',
    r'.familiar\(\)',
    r'.familiar_or\(\)',
    r'phone_numbers\(\)',
    r'formatted_age\(\)'
]

generator_constants.UNMAP_SUFFIXES = {
  ".birthdate.format()": '.birthdate',
  ".age_in_years()": ".birthdate",
  ".address.block()": ".address.address",
  ".address.on_one_line()": ".address.address",
  ".address.line_one()": ".address.address",
  ".address.line_two()": ".address.address",
}