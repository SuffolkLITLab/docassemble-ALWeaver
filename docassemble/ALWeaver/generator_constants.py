"""
Constants for interview_generator.py
"""

from typing import Dict, List


# This is to workaround fact you can't do local import in Docassemble playground
class GeneratorConstantObject(object):
    RESERVED_WHOLE_WORDS: List[str]
    UNDEFINED_PERSON_PREFIXES: List[str]
    ALLOW_SINGULAR_SUFFIXES: List[str]
    RESERVED_PERSON_PLURALIZERS_MAP: Dict[str, str]
    RESERVED_PREFIXES: List[str]
    RESERVED_PRIMITIVE_PLURALIZERS_MAP: Dict[str, str]
    RESERVED_PLURALIZERS_MAP: Dict[str, str]
    RESERVED_SUFFIXES_MAP: Dict[str, str]
    PEOPLE_SUFFIXES_MAP: Dict[str, str]
    PEOPLE_SUFFIXES: List[str]
    DOCX_ONLY_SUFFIXES: List[str]
    DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX: Dict[str, str]
    FULL_DISPLAY: Dict[str, str]
    COURT_CHOICES: List[str]


generator_constants = GeneratorConstantObject()

# Words that are reserved exactly as they are
generator_constants.RESERVED_WHOLE_WORDS = [
    "signature_date",
    "docket_number",
    "case_number",
    "user_needs_interpreter",
    "user_preferred_language",
]

# Prefixes for singular person-like objects, like trial courts that
# should be left undefined to trigger their question
generator_constants.UNDEFINED_PERSON_PREFIXES = [
    "trial_court",
]

# NOTE: if the suffix is allowed for a singular prefix, you must list the variable here
# E.g., we do not allow users.address.address in a DOCX, but we do allow trial_court.address.address
generator_constants.ALLOW_SINGULAR_SUFFIXES = ["trial_court"]

# Prefixes as they would appear in a PDF (singular)
generator_constants.RESERVED_PREFIXES = [
    "users",
    "other_parties",
    "children",
    "plaintiffs",
    "defendants",
    "petitioners",
    "respondents",
    "spouses",
    "parents",
    "caregivers",
    "attorneys",
    "translators",
    "debt_collectors",
    "creditors",
    "witnesses",
    "courts",
    "decedents",
    "interested_partys",
    "interested_parties",
    "trial_court",
    "docket_numbers",
    "case_numbers",
    "user",
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
    "decedent",
    "interested_party",
    "trial_court",
    "adoptees",
    # Can't find a way to make order not matter here
    # without making everything in general more messy
    "guardians_ad_litem",
    "guardian_ad_litem",
    "guardians",
    "guardian",
]

generator_constants.RESERVED_PERSON_PLURALIZERS_MAP = {
    # Singular terms that get pluralized are deprecated
    "users": "users",
    "other_parties": "other_parties",
    "children": "children",
    "plaintiffs": "plaintiffs",
    "defendants": "defendants",
    "petitioners": "petitioners",
    "respondents": "respondents",
    "spouses": "spouses",
    "parents": "parents",
    "caregivers": "caregivers",
    "attorneys": "attorneys",
    "translators": "translators",
    "debt_collectors": "debt_collectors",
    "creditors": "creditors",
    "witnesses": "witnesses",
    "courts": "courts",
    "decedents": "decedents",
    "interested_parties": "interested_parties",
    "guardians_ad_litem": "guardians_ad_litem",
    "guardians": "guardians",
    "adoptees": "adoptees",
    # These are left in for backwards compatibility
    "user": "users",
    "plaintiff": "plaintiffs",
    "defendant": "defendants",
    "petitioner": "petitioners",
    "respondent": "respondents",
    "spouse": "spouses",
    "parent": "parents",
    "guardian": "guardians",
    "caregiver": "caregivers",
    "attorney": "attorneys",
    "translator": "translators",
    "debt_collector": "debt_collectors",
    "creditor": "creditors",
    # Non "s" plurals
    "other_party": "other_parties",
    "child": "children",
    "guardian_ad_litem": "guardians_ad_litem",
    "witness": "witnesses",
    "decedent": "decedents",
    "interested_party": "interested_parties",
    "adoptee": "adoptees",
    # Special for name change forms (maybe HACK)
    "users[0].previous_names": "users[0].previous_names",
    "children[0].previous_names": "children[0].previous_names",
}

generator_constants.RESERVED_PRIMITIVE_PLURALIZERS_MAP = {
    "docket_numbers": "docket_numbers",
    "case_numbers": "case_numbers",
}

generator_constants.RESERVED_PLURALIZERS_MAP = {
    **generator_constants.RESERVED_PERSON_PLURALIZERS_MAP,
    **generator_constants.RESERVED_PRIMITIVE_PLURALIZERS_MAP,
    **{
        "court": "courts",  # for backwards compatibility
    },
}

# Any reason to not make all suffixes available to everyone?
# Yes: it can break variables that overlap but have a different meaning
# Better to be explicit

# Some common attributes that can be a clue it's a person object
generator_constants.PEOPLE_SUFFIXES_MAP = {
    "_name": "",  # full name
    "_name_full": "",  # full name
    "_name_first": ".name.first",
    "_name_middle": ".name.middle",
    "_name_middle_initial": ".name.middle_initial()",
    "_name_last": ".name.last",
    "_name_suffix": ".name.suffix",
    "_gender": ".gender",
    "_gender_male": ".gender_male",
    "_gender_female": ".gender_female",
    "_gender_nonbinary": ".gender_nonbinary",
    "_gender_undisclosed": ".gender_undisclosed",
    "_gender_self_described": ".gender_self_described",
    "_birthdate": ".birthdate.format()",
    "_age": ".age_in_years()",
    "_email": ".email",
    "_language": ".language",
    "_phone": ".phone_number",
    "_phone_number": ".phone_number",
    "_fax_number": ".fax_number",
    "_mobile": ".mobile_number",
    "_mobile_number": ".mobile_number",
    "_phones": ".phone_numbers()",
    "_address_block": ".address.block()",
    # TODO: deprecate street and street2 from existing forms and documentation
    "_address_street": ".address.address",
    "_address_street2": ".address.unit",
    "_address_address": ".address.address",
    "_address_unit": ".address.unit",
    "_address_city": ".address.city",
    "_address_state": ".address.state",
    "_address_zip": ".address.zip",
    "_address_county": ".address.county",
    "_address_country": ".address.country",
    "_address_on_one_line": ".address.on_one_line()",
    "_address_line_one": ".address.line_one()",
    "_address_city_state_zip": ".address.line_two()",
    "_address_line_two": ".address.line_two()",
    "_signature": ".signature",
    "_mailing_address_block": ".mailing_address.block()",
    "_mailing_address_street": ".mailing_address.address",
    "_mailing_address_street2": ".mailing_address.unit",
    "_mailing_address_address": ".mailing_address.address",
    "_mailing_address_unit": ".mailing_address.unit",
    "_mailing_address_city": ".mailing_address.city",
    "_mailing_address_state": ".mailing_address.state",
    "_mailing_address_zip": ".mailing_address.zip",
    "_mailing_address_county": ".mailing_address.county",
    "_mailing_address_country": ".mailing_address.country",
    "_mailing_address_on_one_line": ".mailing_address.on_one_line()",
    "_mailing_address_line_one": ".mailing_address.line_one()",
    "_mailing_address_city_state_zip": ".mailing_address.line_two()",
    "_mailing_address_line_two": ".mailing_address.line_two()",
    "_mailing_address": ".mailing_address",
    "_preferred_name": ".preferred_name",
    "_preferred_name_full": ".preferred_name",
    "_preferred_name_first": ".preferred_name.first",
    "_preferred_name_middle": ".preferred_name.middle",
    "_preferred_name_last": ".preferred_name.last",
    "_preferred_name_suffix": ".preferred_name.suffix",
    "_previous_names1": ".previous_names[0]",  # HACK for LIT Con 2023: we don't have a way to say an attribute is a list yet.
    "_previous_names1_full": ".previous_names[0]",
    "_previous_names1_first": ".previous_names[0].first",
    "_previous_names1_middle": ".previous_names[0].middle",
    "_previous_names1_last": ".previous_names[0].last",
    "_previous_names1_suffix": ".previous_names[0].suffix",
    "_previous_names2": ".previous_names[1]",
    "_previous_names2_full": ".previous_names[1]",
    "_previous_names2_first": ".previous_names[1].first",
    "_previous_names2_middle": ".previous_names[1].middle",
    "_previous_names2_last": ".previous_names[1].last",
    "_previous_names2_suffix": ".previous_names[1].suffix",
    "_previous_names3": ".previous_names[2]",
    "_previous_names3_full": ".previous_names[2]",
    "_previous_names3_first": ".previous_names[2].first",
    "_previous_names3_middle": ".previous_names[2].middle",
    "_previous_names3_last": ".previous_names[2].last",
    "_previous_names3_suffix": ".previous_names[2].suffix",
    "_previous_names4": ".previous_names[3]",
    "_previous_names4_full": ".previous_names[3]",
    "_previous_names4_first": ".previous_names[3].first",
    "_previous_names4_middle": ".previous_names[3].middle",
    "_previous_names4_last": ".previous_names[3].last",
    "_previous_names4_suffix": ".previous_names[3].suffix",
    "_previous_names5": ".previous_names[4]",
    "_previous_names5_full": ".previous_names[4]",
    "_previous_names5_first": ".previous_names[4].first",
    "_previous_names5_middle": ".previous_names[4].middle",
    "_previous_names5_last": ".previous_names[4].last",
    "_previous_names5_suffix": ".previous_names[4].suffix",
    "_consented_to_name_change": ".consented_to_name_change",  # HACK for LITCon 2023: these are name-change specific
    "_parent_consent_attached": ".parent_consent_attached",
    "_no_consent_attached_explanation": ".no_consent_attached_explanation",
}

generator_constants.PEOPLE_SUFFIXES = list(
    generator_constants.PEOPLE_SUFFIXES_MAP.values()
) + [".name.full()", ".name"]

# reserved_suffixes_map
generator_constants.RESERVED_SUFFIXES_MAP = {
    **generator_constants.PEOPLE_SUFFIXES_MAP,
    **{
        # Court-specific
        # '_name_short': not implemented,
        "_division": ".division",
        "_county": ".address.county",
        "_department": ".department",
    },
}

# these might be used in a docx, but we don't transform PDF fields to use these
# suffixes
generator_constants.DOCX_ONLY_SUFFIXES = [
    r"\.birthdate",
    r"\.birthdate.format\(.*\)",
    r"\.familiar\(\)",
    r"\.familiar_or\(\)",
    r"\.phone_numbers\(\)",
    r"\.formatted_age\(\)",
]

generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX = {
    "\.address.block\(\)$": ".address.address",
    "\.address.line_one\(\)$": ".address.address",
    "\.address.line_two\(\)$": ".address.address",
    "\.address.on_one_line\(\)$": ".address.address",
    "\.age_in_years\(\)$": ".birthdate",
    "\.birthdate.format\(.*\)$": ".birthdate",
    "\.familiar_or\(\)$": ".name.first",
    "\.familiar\(\)$": ".name.first",
    "\.formatted_age\(.*\)$": ".birthdate",
    "\.mailing_address.block\(\)$": ".mailing_address.address",
    "\.mailing_address.line_one\(\)$": ".mailing_address.address",
    "\.mailing_address.line_two\(\)$": ".mailing_address.address",
    "\.mailing_address.on_one_line\(\)$": ".mailing_address.address",
    "\.name.middle_initial\(\)$": ".name.first",
    "\.phone_numbers\(\)$": ".phone_number",
    "\.preferred_name$": ".preferred_name.first",
}

# Test needed: Jinja `{{ parents[0].name_of_dog }}` should remain the same,
# not `.name.full()` in the review screen displayed value
generator_constants.FULL_DISPLAY = {
    "\.name$": ".name.full()",
    "\.address$": ".address.block()",
    "\.mailing_address$": ".mailing_address.block()",
}

# Possible values for 'Allowed Courts', when looking up courts to submit to
generator_constants.COURT_CHOICES = [
    "Boston Municipal Court",
    "District Court",
    "Superior Court",
    "Housing Court",
    "Probate and Family Court",
    "Juvenile Court",
    "Land Court",
]
