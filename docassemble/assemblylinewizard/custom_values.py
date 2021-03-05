"""
Container for widely used data that may be altered by user inputs.
"""

# This is to workaround fact you can't do local import in Docassemble playground
class Object(object):
  pass

custom_values = Object()

# Var names of people-type lists that developers add while using the weaver.
# Could be a list, but a dict will match RESERVED_PLURALIZERS_MAP in the
# places it's used, so maybe easier to treat them both the same.
custom_values.people_plurals_map = {}
