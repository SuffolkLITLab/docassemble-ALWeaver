import os
import re
import keyword
import copy
import uuid
import sys
import yaml
import tempfile
from collections import defaultdict
from docx2python import docx2python
from docassemble.webapp.files import SavedFile, get_ext_and_mimetype, make_package_zip
from docassemble.base.pandoc import word_to_markdown, convertible_mimetypes, convertible_extensions
from docassemble.base.error import DAError
from docassemble.base.util import log, space_to_underscore, bold, DAObject, DADict, DAList, DAFile, DAFileList
import docassemble.base.functions
import docassemble.base.parse
import docassemble.base.pdftk
from docassemble.base.core import DAEmpty
import shutil
import datetime
import zipfile
import types
import json
from typing import Dict, List, Set, Tuple
from .generator_constants import generator_constants
from .custom_values import custom_values

TypeType = type(type(None))

__all__ = ['Playground', 'PlaygroundSection', 'indent_by', 'varname', 'DAField', 'DAFieldList', \
           'DAQuestion', 'DAInterview', 'DAAttachmentList', 'DAAttachment', 'to_yaml_file', \
           'base_name', 'escape_quotes', 'oneline', 'DAQuestionList', 'map_raw_to_final_display', \
           'is_reserved_label', 'attachment_download_html', \
           'get_fields', 'get_pdf_fields', 'is_reserved_docx_label','get_character_limit', \
           'create_package_zip', \
           'get_person_variables', 'get_court_choices',\
           'process_custom_people', 'set_custom_people_map',\
           'map_names']

always_defined = set(["False", "None", "True", "dict", "i", "list", "menu_items", "multi_user", "role", "role_event", "role_needed", "speak_text", "track_location", "url_args", "x", "nav", "PY2", "string_types"])
replace_square_brackets = re.compile(r'\\\[ *([^\\]+)\\\]')
end_spaces = re.compile(r' +$')
spaces = re.compile(r'[ \n]+')
invalid_var_characters = re.compile(r'[^A-Za-z0-9_]+')
digit_start = re.compile(r'^[0-9]+')
newlines = re.compile(r'\n')
remove_u = re.compile(r'^u')

def get_court_choices():
  return generator_constants.COURT_CHOICES

def attachment_download_html(url, label):
  return '<a href="' + url + '" download="">' + label + '</a>'

def get_character_limit(pdf_field_tuple, char_width=6, row_height=12):
  """
  Take the pdf_field_tuple and estimate the number of characters that can fit
  in the field, based on the x/y bounding box.

  0: horizontal start
  1: vertical start
  2: horizontal end
  3: vertical end
  """
  # Make sure it's the right kind of tuple
  if len(pdf_field_tuple) < 3 or (pdf_field_tuple[3] and len(pdf_field_tuple[3]) < 4):
    return None # we can't really guess

  # Did a little testing for typical field width/number of chars with both w and e.
  # 176 = 25-34 chars. from w to e
  # 121 = 17-22
  # Average about 6 pixels width per character
  # about 12 pixels high is one row

  length = pdf_field_tuple[3][2] - pdf_field_tuple[3][0]
  height = pdf_field_tuple[3][3] - pdf_field_tuple[3][1]
  num_rows = int(height / row_height) if height > 12 else 1
  num_cols = int(length / char_width )

  max_chars = num_rows * num_cols
  return max_chars


class DAAttachment(DAObject):
    """This class represents the attachment block we will create in the final output YAML"""
    def init(self, **kwargs):
        return super().init(**kwargs)

class DAAttachmentList(DAList):
    """This is a list of DAAttachment objects"""
    def init(self, **kwargs):
        super().init(**kwargs)
        self.object_type = DAAttachment
        self.auto_gather = False
    def url_list(self, project='default'):
        output_list = list()
        for x in self.elements:
            if x.type == 'md':
                output_list.append('[`' + x.markdown_filename + '`](' + docassemble.base.functions.url_of("playgroundfiles", section="template", file=x.markdown_filename, project=project) + ')')
            elif x.type == 'pdf':
                output_list.append('[`' + x.pdf_filename + '`](' + docassemble.base.functions.url_of("playgroundfiles", section="template", project=project) + ')')
            elif x.type == 'docx':
                output_list.append('[`' + x.docx_filename + '`](' + docassemble.base.functions.url_of("playgroundfiles", section="template", project=project) + ')')
        return docassemble.base.functions.comma_and_list(output_list)

class DAInterview(DAObject):
    """ This class represents the final YAML output. It has a method to output to a string."""
    def init(self, **kwargs):
        self.blocks = DAQuestionList(auto_gather=False, gathered=True, is_mandatory=False)
        self.questions = DAQuestionList(auto_gather=False, gathered=True, is_mandatory=False)
        self.final_screen = DAQuestion()
        #self.decorations = DADecorationDict()
        self.target_variable = None
        return super().init(**kwargs)
    def has_decorations(self):
        return False
        # if self.decorations.gathered and len(self.decorations) > 0:
        #     return True
        # return False
    def decoration_list(self):
        out_list = [["None", "No decoration"]]
        for key, data in self.decorations.items():
            out_list.append([key, '[EMOJI ' + str(data.fileref) + ', 1em] ' + str(key)])
        return out_list
    def package_info(self):
        info = dict()
        for field in ['dependencies', 'interview_files', 'template_files', 'module_files', 'static_files']:
            if field not in info:
                info[field] = list()
        info['author_name'] = ""                
        info['readme'] = ""
        info['description'] = self.title
        info['version'] = "1.0"
        info['license'] = "The MIT License"
        info['url'] = "https://courtformsonline.org"
        # File structure below isn't helpful for files that aren't installed
        # on the local playground. We need to replace with DAFiles, not a list of file names
        # for block in self.all_blocks():
        #     if hasattr(block, 'templates_used'):
        #         for template in block.templates_used:
        #             if not re.search(r'^docassemble\.', template):
        #                 info['template_files'].append(template)
        #     if hasattr(block, 'static_files_used'):
        #         for static_file in block.static_files_used:
        #             if not re.search(r'^docassemble\.', static_file):
        #                 info['static_files'].append(static_file)
        # info['interview_files'].append(self.yaml_file_name())
        return info
    def yaml_file_name(self):
        return to_yaml_file(self.file_name)
    def all_blocks(self):
        return self.blocks + self.questions.elements
        # seen = set()
        # out = list()
        # for block in self.blocks:
        #     if block not in seen:
        #         out.append(block)
        #         seen.add(block)
        # for var in self.questions.elements:# sorted(self.questions.keys()):
        #     #if var not in seen:
        #     #    out.append(var)
        #     #    seen.add(var)
        # return out
    def demonstrate(self):
        for block in self.all_blocks():
            block.demonstrated
    def source(self):
        """This method creates a YAML string that represents the entire interview"""
        return "---\n".join(map(lambda x: x.source(), self.all_blocks()))
    def known_source(self, skip=None):
        output = list()
        for block in self.all_blocks():
            if block is skip:
                continue
            try:
                output.append(block.source(follow_additional_fields=False))
            except:
                pass
        return "---\n".join(output)

class DAField(DAObject):
  """A field represents a Docassemble field/variable. I.e., a single piece of input we are gathering from the user.
  Has several important attributes that need to be set:
  * `raw_field_names`: list of field names directly from the PDF or the template text directly from the DOCX.
    In the case of PDFs, there could be multiple, i.e. `child__0` and `child__1`
  * `variable`: the field name that has been turned into a valid identifier, spaces to `_` and stripped of
    non identifier characters
  * `final_display_var`: the docassamble python code that computes exactly what the author wants in their PDF
  
  In many of the methods, you'll also find two other common versions of the field, computed on the fly:
  * `trigger_gather`: returns the statement that causes docassemble to correctly ask the question for this variable, 
     e.g. `users.gather()` to get the `user.name.first`
  * `settable_var`: the settable / assignable data backing `final_display_var`, e.g. `address.address` for `address.block()`
  * `full_visual`: shows the full version of the backing data in a readable way, i.e. `address.block()` for `address.zip`
    TODO(brycew): not fully implemented yet
  """
  def init(self, **kwargs):
    return super().init(**kwargs)

  def fill_in_docx_attributes(self, new_field_name: str,
                              reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP):
    """The DAField class expects a few attributes to be filled in.
    In a future version of this, maybe we can use context to identify
    true/false variables. For now, we can only use the name.
    We have a lot less info than for PDF fields.
    """
    self.raw_field_names : List[str] = [new_field_name]
    # For docx, we can't change the field name from the document itself, has to be the same
    self.variable : str = new_field_name 
    self.final_display_var : str = new_field_name  
    self.has_label : bool = True

    # variable_name_guess is the placeholder label for the field
    variable_name_guess = self.variable.replace('_', ' ').capitalize()
    if self.variable.endswith('_date'):
      self.field_type_guess = 'date'
      self.variable_name_guess = 'Date of ' + self.variable[:-5].replace('_', ' ')
    elif self.variable.endswith('.signature'):
      self.field_type_guess = "signature"
      self.variable_name_guess = variable_name_guess
    else:
      self.field_type_guess = 'text'
      self.variable_name_guess = variable_name_guess

  def fill_in_pdf_attributes(self, pdf_field_tuple):
    """Let's guess the type of each field from the name / info from PDF"""
    # The raw name of the field from the PDF: must go in attachment block
    self.raw_field_names : List[str] = [pdf_field_tuple[0]]
    # turns field_name into a valid python identifier: must be one per field
    self.variable : str = remove_multiple_appearance_indicator(varname(self.raw_field_names[0]))
    # the variable, in python: i.e., users[1].name.first
    self.final_display_var : str = map_raw_to_final_display(self.variable)

    variable_name_guess = self.variable.replace('_', ' ').capitalize()
    self.has_label = True
    if self.variable.endswith('_date'):
        self.field_type_guess = 'date'
        self.variable_name_guess = 'Date of ' + self.variable[:-5].replace('_', ' ')
    elif self.variable.endswith('_yes') or self.variable.endswith('_no'):
        self.field_type_guess = 'yesno'
        name_no_suffix = self.variable[:-3] if self.variable.endswith('_no') else self.variable[:-4]
        self.variable_name_guess = name_no_suffix.replace('_', ' ').capitalize()
    elif pdf_field_tuple[4] == '/Btn':
        self.field_type_guess = 'yesno'
        self.variable_name_guess = variable_name_guess
    elif pdf_field_tuple[4] == "/Sig":
        self.field_type_guess = "signature"
        self.variable_name_guess = variable_name_guess
    else:
        self.field_type_guess = 'text'
        self.variable_name_guess = variable_name_guess
    self.maxlength = get_character_limit(pdf_field_tuple)
    
  def mark_as_paired_yesno(self, paired_field_names: List[str]):
    """Marks this field as actually representing multiple template fields:
    some with `variable_name`_yes and some with `variable_name`_no
    """
    self.paired_yesno = True
    if self.variable.endswith('_no'):
      self.raw_field_names = paired_field_names + self.raw_field_names
      self.variable = self.variable[:-3] 
      self.final_display_var = self.final_display_var[:-3]
    elif self.variable.endswith('_yes'):
      self.raw_field_names = self.raw_field_names + paired_field_names
      self.variable = self.variable[:-4]
      self.final_display_var = self.final_display_var[:-4]

  def mark_with_duplicate(self, duplicate_field_names: List[str]):
    """Marks this field as actually representing multiple template fields, and 
    hanging on to the original names of all of the duplicates
    """
    self.raw_field_names += duplicate_field_names

  def get_single_field_screen(self):
    settable_version = self.get_settable_var() 
    if self.field_type == 'yesno':
      return "yesno: {}\n".format(settable_version), True
    elif self.field_type == 'yesnomaybe':
      return "yesnomaybe: {}\n".format(settable_version), True
    else:
      return "", False

  def _maxlength_str(self) -> str:
    if hasattr(self, 'maxlength') and self.maxlength:
      return "    maxlength: {}".format(self.maxlength)
    else:
      return ""

  def field_entry_yaml(self) -> str:
    settable_var = self.get_settable_var()
    content = ""
    if self.has_label:
      content += '  - "{}": {}\n'.format(escape_quotes(self.label), settable_var)
    else:
      content += "  - no label: {}\n".format(settable_var)
    # Use all of these fields plainly. No restrictions/validation yet
    if self.field_type in ['yesno', 'yesnomaybe', 'file']:
      content += "    datatype: {}\n".format(self.field_type)
    elif self.field_type == 'area':
      content += "    input type: area\n"
      content += self._maxlength_str() + '\n'
    elif self.field_type in ['integer', 'currency', 'email', 'range', 'number', 'date']:
      content += "    datatype: {}\n".format(self.field_type)
      if self.field_type in ['integer', 'currency']:
        content += "    min: 0\n"
      elif self.field_type == 'email':
        content += self._maxlength_str() + '\n'
      elif self.field_type == 'range':
        content += "    min: {}\n".format(self.range_min)
        content += "    max: {}\n".format(self.range_max)
        content += "    step: {}\n".format(self.range_step)
    else:  # a standard text field
      content += self._maxlength_str() + '\n'
    
    return content

  def review_viewing(self, full_display_map=generator_constants.FULL_DISPLAY):
    settable_var = self.get_settable_var()
    parent_var, _ = DAField._get_parent_variable(settable_var)

    full_display = substitute_suffix(parent_var, full_display_map)

    edit_display_name = self.label if hasattr(self, 'label') else settable_var
    content = indent_by(escape_quotes(bold(edit_display_name)) + ': ', 6)
    if hasattr(self, 'field_type'):
      if self.field_type in ['yesno', 'yesnomaybe']:
        content += indent_by('${ word(yesno(' + full_display + ')) }', 6)
      elif self.field_type in ['integer', 'number','range']:
        content += indent_by('${ ' + full_display + ' }', 6)
      elif self.field_type == 'area':
        content += indent_by('> ${ single_paragraph(' + full_display + ') }', 6)
      elif self.field_type == 'file':
        content += "      \n"
        content += indent_by('${ ' + full_display + ' }', 6)
      elif self.field_type == 'currency':
        content += indent_by('${ currency(' + full_display + ') }', 6)
      elif self.field_type == 'date':
        content += indent_by('${ ' + full_display + ' }', 6)
      # elif field.field_type == 'email':
      else:  # Text
        content += indent_by('${ ' + full_display + ' }', 6)
    else:
      content += indent_by('${ ' + self.final_display_var + ' }', 6)
    return content

  def attachment_yaml(self):
    # Lets use the list-style, not dictionary style fields statement
    # To avoid duplicate key error
    if hasattr(self, 'paired_yesno') and self.paired_yesno:
      content = ''
      for raw_name in self.raw_field_names:
        var_name = remove_multiple_appearance_indicator(varname(raw_name))
        if var_name.endswith('_yes'):
          content += '      - "{}": ${{ {} }}\n'.format(raw_name, self.final_display_var)
        elif var_name.endswith('_no'):
          content += '      - "{}": ${{ not {} }}\n'.format(raw_name, self.final_display_var)
      return content

    # Handle multiple indicators
    format_str = '      - "{}": '
    if hasattr(self, 'field_type') and self.field_type == 'date':
      format_str += '${{ ' + self.variable.format() + ' }}\n'
    elif hasattr(self, 'field_type') and self.field_type == 'currency':
      format_str += '${{ currency(' + self.variable + ') }}\n'
    elif hasattr(self, 'field_type') and self.field_type == 'number':
      format_str += r'${{ "{{:,.2f}}".format(' + self.variable + ') }}\n' 
    elif self.field_type_guess == 'signature': 
      comment = "      # It's a signature: test which file version this is; leave empty unless it's the final version)\n"
      format_str = comment + format_str + '${{ ' + self.final_display_var + " if i == 'final' else '' }}\n"
    else:
      format_str += '${{ ' + self.final_display_var + ' }}\n'

    content = ''
    for raw_name in self.raw_field_names:
      content += format_str.format(raw_name)
    
    return content

  def user_ask_about_field(self, index):
    field_questions = []
    settable_var = self.get_settable_var() 
    if hasattr(self, 'paired_yesno') and self.paired_yesno:
      field_title = '{} (will be expanded to include _yes and _no)'.format(self.final_display_var)
    elif len(self.raw_field_names) > 1:
      field_title = '{} (will be expanded to all instances)'.format(settable_var)
    elif self.raw_field_names[0] != settable_var:
      field_title = '{} (will be renamed to {})'.format(settable_var, self.raw_field_names[0])
    else:
      field_title = self.final_display_var

    field_questions.append({
      'note': bold(field_title)
    })
    field_questions.append({
      'label': "On-screen prompt",
      'field': 'fields[' + str(index) + '].label',
      'default': self.variable_name_guess
    })
    field_questions.append({
      'label': "Field Type",
      'field': 'fields[' + str(index) + '].field_type',
      'choices': ['text', 'area', 'yesno', 'integer', 'number', 'currency', 'date', 'email'], 
      'default': self.field_type_guess if hasattr(self, 'field_type_guess') else None
    })
    return field_questions

  def trigger_gather(self,
                     custom_people_plurals_map=custom_values.people_plurals_map,
                     reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
                     undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
                     reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS,
                     reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP):
    """Turn the docassemble variable string into an expression
    that makes DA ask a question for it. This is mostly
    calling `gather()` for lists"""
    # TODO: we might want to think about how to handle the custom names differently
    # in the future. This lets us avoid having to specify the full/combined list of people
    # exact prefix matches are dealt with easily
    if hasattr(self, 'custom_trigger_gather'):
      return self.custom_trigger_gather
    GATHER_CALL = '.gather()'
    if self.final_display_var in reserved_whole_words:
      return self.final_display_var

    if (self.final_display_var in reserved_var_plurals
         or self.final_display_var in custom_people_plurals_map.values()):
      return self.final_display_var + GATHER_CALL

    # Deal with more complex matches to prefixes
    # Everything before the first period and everything from the first period to the end
    var_with_attribute = self.get_settable_var()
    var_parts = re.findall(r'([^.]+)(\.[^.]*)?', var_with_attribute)

    # test for existence (empty strings result in a tuple)
    if not var_parts:
      return self.final_display_var
    # The prefix, ensuring no key or index
    prefix = re.sub(r'\[.+\]', '', var_parts[0][0])
    has_plural_prefix = prefix in reserved_pluralizers_map.values() or prefix in custom_people_plurals_map.values()
    has_singular_prefix = prefix in undefined_person_prefixes

    if has_plural_prefix or has_singular_prefix:
      first_attribute = var_parts[0][1]
      if has_plural_prefix and (first_attribute == '' or first_attribute == '.name'):
        return prefix + GATHER_CALL
      elif first_attribute == '.address' or first_attribute == '.mail_address':
        return var_parts[0][0] + first_attribute + '.address'
      else:
        return var_parts[0][0] + first_attribute
    else:
      return self.final_display_var

  def get_settable_var(self, display_to_settable_suffix=generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX):
    return substitute_suffix(self.final_display_var, display_to_settable_suffix)
  
  def _get_attributes(self, full_display_map=generator_constants.FULL_DISPLAY):
    """Returns attributes of this DAField, notably without the leading "prefix", or object name
    * the plain attribute, not ParentCollection, but the direct attribute of the ParentCollection
    * the "full display", an expression that shows the whole attribute in human readable form
    * an expression that causes DA to set to this field
    
    For example: the DAField `user[0].address.zip` would return ('address', 'address.block()', 'address.address')
    """
    label_parts = re.findall(r'([^.]*)(\..*)*', self.get_settable_var())

    prefix_with_index = label_parts[0][0] 

    settable_attribute = label_parts[0][1].lstrip('.')
    if settable_attribute == '' or settable_attribute == 'name':
      settable_attribute = 'name.first'
    if settable_attribute == 'address' or settable_attribute == 'mail_address':
      settable_attribute += '.address'
    plain_att = re.findall(r'([^.]*)(\..*)*', settable_attribute)[0][0]
    full_display_att = substitute_suffix('.' + plain_att, full_display_map).lstrip('.')
    return (plain_att, full_display_att, settable_attribute)


  @staticmethod
  def _get_parent_variable(var_with_attribute: str,
                           custom_people_plurals_map=custom_values.people_plurals_map,
                           undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
                           reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP) -> Tuple[str, str]:
    """Gets the parent object or list that holds the data that is in var_with_attribute, as well
    as what type the object is
    For example, `users[0].name` and `users[1].name.last` will both return `users`. 
    """
    var_parts = re.findall(r'([^.]+)(\.[^.]*)?', var_with_attribute)
    if not var_parts:
      return var_with_attribute 
    
    # Either indexed, or no need to be indexed
    indexed_var = var_parts[0][0]

    # The prefix, ensuring no key or index
    prefix = re.sub(r'\[.+\]', '', indexed_var)
    
    has_plural_prefix = prefix in reserved_pluralizers_map.values() or prefix in custom_people_plurals_map.values()
    has_singular_prefix = prefix in undefined_person_prefixes
    if has_plural_prefix:
      return prefix, 'list'
    if has_singular_prefix:
      return prefix, 'object'
    return var_with_attribute, 'primitive'


class ParentCollection(object):
  """A ParentCollection is "highest" level of data structure containing some DAField.
  For example, the parent collection for `users[0].name.first` is `users`, since that is the list 
  that contains the user object of the `name` attribute that we are referencing.

  Some other examples: `trial_court` is the parent of `trial_court.division`, and for primitive
  variables like `my_string`, the parent collection is just `my_string`.

  The parent collection is useful for review screens, where we want to group related fields 
  """
  def __init__(self, var_name: str, var_type: str, fields: List[DAField]):
    """Constructor:
    @param var_name: the name of this parent collection variable
    @param var_type: the type of this parent collection variable. Can be 'list', 'object', or 'primitive'
    @param fields: the DAFields that all share this parent collection variable
    """
    self.var_name = var_name
    self.fields = fields
    self.attribute_map = {}
    self.var_type = var_type
    if self.var_type != 'primitive':  # this base var is more complex than a simple primitive type
      for f in self.fields:
        plain_att, disp_att, settable_att = f._get_attributes()
        self.attribute_map[plain_att] = (disp_att, settable_att)

  def revisit_page(self) -> str:
    if self.var_type != 'list':
      return ''

    content = """---
field: {0}.revisit
question: |
  Edit {0}
subquestion: |
  ${{ {0}.table }}

  ${{ {0}.add_action() }}
"""
    return content.format(self.var_name)


  def table_page(self) -> str:
    if self.var_type != 'list':
      return ''
    content = """---
table: {var_name}.table
rows: {var_name}
columns:
{all_columns}
edit:
{settable_list}
confirm: True
"""
    all_columns = ''
    settable_list = ''
    for att, disp_and_set in self.attribute_map.items():
      all_columns += '  - {0}: |\n'.format(att)
      all_columns += '      row_item.{0} if defined("row_item.{1}") else ""\n'.format( disp_and_set[0], disp_and_set[1])
      settable_list += '  - {}\n'.format(disp_and_set[1])
    return content.format(var_name=self.var_name, all_columns=all_columns, settable_list=settable_list)


  def review_yaml(self): 
    """Generate the yaml entry for this object in the review screen list"""
    if self.var_type == 'list':
      edit_attribute = self.var_name + '.revisit'
    else:
      edit_attribute = self.var_name
      
    content = '  - Edit: ' + edit_attribute + "\n"
    content += '    button: |\n'
        
    if self.var_type == 'list': 
      content += indent_by(bold(self.var_name), 6) + '\n'
      content += indent_by("% for item in {}:".format(self.var_name), 6)
      content += indent_by("* ${ item }", 8)
      content += indent_by("% endfor", 6)
      return content
    
    if self.var_type == 'object':
      content += indent_by(bold(self.var_name), 6) + '\n'
      for att, disp_set in self.attribute_map.items():
        content += indent_by('% if defined("{}.{}"):'.format(self.var_name, disp_set[1]), 6)
        content += indent_by('* {}: ${{ {}.{} }}'.format(att, self.var_name, disp_set[0]), 6)
        content += indent_by('% endif', 6)
      return content
    
    return content + self.fields[0].review_viewing()


class DAFieldList(DAList):
  """A DAFieldList contains multiple DAFields."""
  def init(self, **kwargs):
    self.object_type = DAField
    self.auto_gather = False
    # self.gathered = True
    return super().init(**kwargs)
  def __str__(self):
    return docassemble.base.functions.comma_and_list(map(lambda x: '`' + x.variable + '`', self.elements))

  def __add__(self, other):
    """Needed to make sure that DAFieldLists stay DAFieldLists when adding them"""
    self._trigger_gather()
    if isinstance(other, DAEmpty):
      return self
    if isinstance(other, DAFieldList):
      other._trigger_gather()
      the_list = DAFieldList(elements=self.elements + other.elements, gathered=True, auto_gather=False)
      the_list.set_random_instance_name()
      return the_list
    return self.elements + other
    
  def consolidate_yesnos(self):
    """Combines separate yes/no questions into a single variable, and writes back out to the yes
    and no variables"""
    yesno_map = defaultdict(list)
    mark_to_remove: List[int] = []
    for idx, field in enumerate(self.elements):
      if not field.variable.endswith('_yes') and not field.variable.endswith('_no'):
        continue

      if len(yesno_map[field.variable_name_guess]) == 1:
        yesno_map[field.variable_name_guess][0].mark_as_paired_yesno(field.raw_field_names)
      yesno_map[field.variable_name_guess].append(field)

      if len(yesno_map[field.variable_name_guess]) > 1:
        mark_to_remove.append(idx)

    self.delitem(*mark_to_remove)
    self.there_are_any = len(self.elements) > 0


  def consolidate_duplicate_fields(self, document_type: str = 'pdf'):
    """Removes all duplicate fields from a PDF (docx's are handled elsewhere) that really just 
    represent a single variable, leaving one remaining field that writes all of the original vars
    """
    if document_type.lower() == 'docx':
      return
  
    field_map: Dict[str, DAField] = {}
    mark_to_remove: List[int] = []
    for idx, field in enumerate(self.elements):
      if field.final_display_var in field_map.keys():
        field_map[field.final_display_var].mark_with_duplicate(field.raw_field_names)
        mark_to_remove.append(idx)
      else:
        field_map[field.final_display_var] = field
    self.delitem(*mark_to_remove)
    self.there_are_any = len(self.elements) > 0


  def find_parent_collections(self) -> List[ParentCollection]:
    """Gets all of the individual ParentCollections from the DAFields in this list."""
    parent_coll_map = defaultdict(list)
    for field in self.elements:
      parent_var_and_type = DAField._get_parent_variable(field.final_display_var)
      parent_coll_map[parent_var_and_type].append(field)

    return [ParentCollection(var_and_type[0], var_and_type[1], fields) 
            for var_and_type, fields in parent_coll_map.items()]

    
  def delitem(self, *pargs):
    """TODO(brycew): remove when all of our servers are on 1.2.35, it's duplicating
    https://github.com/jhpyle/docassemble/blob/8e7e4f5ee90803022779bac57308b73b41f92da8/docassemble_base/docassemble/base/core.py#L1127-L1131"""
    for item in reversed([item for item in pargs if item < len(self.elements)]):
      self.elements.__delitem__(item)
    self._reset_instance_names()
    

class DAQuestion(DAObject):
    """This class represents a "question" in the generated YAML file. TODO: move
    some of the "questions" into other block types. """

    # TODO: subclass question or come up with other types for things
    # that aren't really questions instead of giant IF block
    # TODO: separate out some of the code specific to the assembly-line project
    # into its own module or perhaps interview YAML
    def init(self, **kwargs):
        self.field_list = DAFieldList()
        self.templates_used = set()
        self.static_files_used = set()
        return super().init(**kwargs)

    def source(self, follow_additional_fields=True, document_type="pdf"):
        """This method outputs the YAML code representing a single "question" in the interview."""
        content = ''
        if hasattr(self, 'progress'):
            content += 'progress: ' + self.progress + '\n'
        if hasattr(self, 'is_mandatory') and self.is_mandatory:
            content += "mandatory: True\n"
        # TODO: refactor. Too many things shoved into "question"
        if self.type == 'question':
            done_with_content = False
            if hasattr(self, 'id') and self.id:
                # TODO: ask for ID in the wizard
                content += "id: " + fix_id(self.id) + "\n"
            else:
                content += "id: " + fix_id(self.question_text) + "\n"
            if hasattr(self, 'event'):
                content += "event: " + self.event + "\n"
            if self.needs_continue_button_field:
              content += "continue button field: " + varname(self.question_text) + "\n"
            elif hasattr(self, 'continue_button_field'):
              content += "continue button field: " + varname(self.continue_button_field) + "\n"
            content += "question: |\n" + indent_by(self.question_text, 2)
            if self.subquestion_text != "":
                content += "subquestion: |\n" + indent_by(self.subquestion_text, 2)
            if self.field_list.number() == 0:
              done_with_content = True
            else:
              if self.field_list.number() == 1:
                  new_content, done_with_content = self.field_list[0].get_single_field_screen()
                  content += new_content
              if self.field_list[0].field_type == 'end_attachment':
                  #if hasattr(self, 'interview_label'):  # this tells us its the ending screen
                  #  # content += "buttons:\n  - Exit: exit\n  - Restart: restart\n" # we don't want people to erase their session
                  #  # TODO: insert the email code
                  #  #content += "attachment code: " + self.attachment_variable_name + "['final']\n"
                  #if (isinstance(self, DAAttachmentList) and self.attachments.gathered and len(self.attachments)) or (len(self.attachments)):
                  # attachments is no longer always a DAList
                  # TODO / FUTURE we could let this handle multiple forms at once
                  for attachment in self.attachments:  # We will only have ONE attachment
                      # TODO: if we really use multiple attachments, we need to change this
                      # So there is a unique variable name
                      content += "---\n"
                      # Use a DADict to store the attachment here
                      content += "objects:\n"
                      # TODO: has_addendum should be a flag set in the generator, not hardcoded
                      content += "  - " + self.attachment_variable_name + ': ALDocument.using(title="' + self.interview.description + '", filename="' + self.interview.file_name + '", enabled=True, has_addendum=False)\n'
                      content += "---\n"
                      content += "objects:\n"
                      # TODO: 
                      content += '  - al_user_bundle: ALDocumentBundle.using(elements=[' + self.attachment_variable_name + '], filename="' + self.interview.file_name + '.pdf", title="All forms to download for your records")' + '\n'
                      content += '  - al_court_bundle: ALDocumentBundle.using(elements=[' + self.attachment_variable_name + '], filename="' + self.interview.file_name + '.pdf", title="All forms to download for your records")' + '\n'
                      content += "---\n"
                      content += "#################### attachment block ######################\n"
                      content += "attachment:\n"
                      content += "    variable name: " + self.attachment_variable_name + "[i]\n"
                      content += "    name: " + oneline(attachment.name) + "\n"
                      content += "    filename: " + varname(attachment.name).replace('_', '-') + "\n"
                      if attachment.type == 'md':
                          content += "    content: " + oneline(attachment.content) + "\n"
                      elif attachment.type == 'pdf':
                          content += "    skip undefined: True" + "\n"
                          content += "    pdf template file: " + oneline(attachment.pdf_filename) + "\n"
                          self.templates_used.add(attachment.pdf_filename)
                          content += "    fields:" + "\n"
                          for field in attachment.fields:
                            content += field.attachment_yaml()
                      elif attachment.type == 'docx':
                          content += "    docx template file: " + oneline(attachment.docx_filename) + "\n"
                          self.templates_used.add(attachment.docx_filename)
                  done_with_content = True
            if not done_with_content:
                content += "fields:\n"  # TODO: test removing \n here
                for field in self.field_list:
                    content += field.field_entry_yaml()

        elif self.type == 'signature':
            content += "signature: " + varname(self.field_list[0].raw_field_names[0]) + "\n"
            self.under_text
            content += "question: |\n" + indent_by(self.question_text, 2)
            if self.subquestion_text != "":
                content += "subquestion: |\n" + indent_by(self.subquestion_text, 2)
            if self.under_text:
                content += "under: |\n" + indent_by(self.under_text, 2)
        elif self.type == 'code':
            content += "code: |\n" + indent_by(self.code, 2)
        elif self.type == 'objects' and len(self.objects):
            # An object should be a list of DAObjects with the following attributes:
            # name, type, params [optional]
            # params is going to be a list/iterable object of two or 3 item tuples or lists 
            # of strings
            # param[0] is the parameter name (argument to .using), param[1] is the value
            # If the param has 3 parts, then param[1] will be treated as a literal rather than
            # string value. string is default. Actual value of param[2] is reserved for future need
            content += "objects:\n"
            for object in self.objects:
              content += "  - " + object.name + ': ' + object.type
              if hasattr(object, 'params'):
                content += ".using("
                params_string_builder = []
                for param in object.params:
                  param_string = str(param[0]) + "="
                  if len(param) > 2:
                    # This might be an int value, other variable name, etc.
                    param_string += str(param[1])
                  else:
                    # this is a normal string value and should get quoted.
                    # use json.dumps() to properly quote strings. shouldn't come up
                    param_string += json.dumps(str(param[1]))
                  params_string_builder.append(param_string)
                content += ",".join(params_string_builder)
                content += ")"
              content += "\n" 
            if not content.endswith("\n"):              
              content += "\n"
            
        elif self.type == 'main order':
          lines = [
            "###################### Main order ######################\n"
            "mandatory: True",
            "comment: |",
            "  This block includes the logic for standalone interviews.",
            "  Delete mandatory: True to include in another interview",
            "id: main_order_" + self.interview_label,
            "code: |",
            "  " + self.intro,
            "  " + self.interview_label + "_intro",
            "  # Interview order block has form-specific logic controlling order/branching",
            "  interview_order_" + self.interview_label,
            "  signature_date", # TODO: do we want this here?
            "  # Save (anonymized) interview statistics.",
            "  store_variables_snapshot(data={'zip': users[0].address.zip})",
            "  " + self.interview_label + "_preview_question  # Pre-canned preview screen",
            "  basic_questions_signature_flow",
          ]
          
          for signature_field in self.signatures:
            lines.append( "  " + signature_field )
          lines.append("  " + self.interview_label + "_download")
          
          content += '\n'.join(lines) + '\n'
                                   
        elif self.type == 'interview order':
            # TODO: refactor this. Too much of it is assembly-line specific code
            # move into the interview YAML or a separate module/subclass
            content += "#################### Interview order #####################\n"
            content += "comment: |\n"
            content += "  Controls order and branching logic of questions in the interview\n"
            content += "id: interview_order_" + self.interview_label + "\n"
            content += "code: |\n"
            added_field_names = set()
            for field in self.logic_list:
              if field == 'signature_date' or field.endswith('.signature'):  # signature stuff goes in main block
                continue
              if not field in added_field_names:
                # We built this logic list by collecting the first field on each screen
                content += "  " + field + "\n"
              added_field_names.add(field)
            content += "  interview_order_" + self.interview_label + " = True" + "\n"
        elif self.type == 'text_template':
            content += "template: " + varname(self.field_list[0].raw_field_names[0]) + "\n"
            if hasattr(self, 'template_subject') and self.template_subject:
                content += "subject: " + oneline(self.template_subject) + "\n"
            if self.template_type == 'file':
                content += "content file: " + oneline(self.template_file) + "\n"
            else:
                content += "content: |\n" + indent_by(self.template_body, 2)
        elif self.type == 'template':
            content += "template: " + varname(self.field_list[0].raw_field_names[0]) + "\n"
            content += "content file: " + oneline(self.template_file) + "\n"
            self.templates_used.add(self.template_file)
        elif self.type == 'sections':
            # content += "features:\n  navigation: True\n"
            # content += '---\n'
            content += "sections:\n"
            for section in self.sections:
                if isinstance(section, dict):
                    for key in section: # Should just be one key
                        content += '  - ' + str(key) + ': ' + str(section[key]) + "\n"
                elif isinstance(section, str):
                    content += '  - ' + section
        elif self.type == 'metadata':
            if hasattr(self, 'comment'):
                content += 'comment: |\n'
                content += indent_by(self.comment, 2)
            content += "metadata:\n"
            for setting in self.settings:
                content += '  ' + setting + ': |\n'
                content += indent_by(self.settings[setting], 4)
            if self.categories.any_true():
              content += "  tags:\n"
              for category in self.categories.true_values():
                content += indent_by("- " + category, 4)
        elif self.type == 'metadata_code':
            # TODO: this is begging to be refactored into
            # just dumping out a dictionary in json-like format
            # rather than us hand-writing the data structure
            # Note 2/23/21: machine-written JSON is not pretty. 
            # So one argument for keeping it handwritten
            if hasattr(self, 'comment'):
                content += 'comment: |\n'
                content += indent_by(self.comment, 2)
            # We need this block to run every time to build our metadata variable
            content += "mandatory: True\n"
            content += "code: |\n"
            content += "  interview_metadata # make sure we initialize the object\n"
            content += "  if not defined(\"interview_metadata['"+ self.interview_label +  "']\"):\n"
            content += "    interview_metadata.initializeObject('" + self.interview_label + "')\n"
            content += "  interview_metadata['" + self.interview_label + "'].update({\n"
            content += '    "title": "' + escape_quotes(oneline(self.title)) + '",\n'
            content += '    "short title": "' + escape_quotes(oneline(self.short_title)) + '",\n'
            content += '    "description": "' + escape_quotes(oneline(self.description)) + '",\n'
            content += '    "original_form": "' + escape_quotes(oneline(self.original_form)) + '",\n'
            content += '    "allowed courts": ' + '[\n'
            for court in self.allowed_courts.true_values():
              content += '      "' + escape_quotes(oneline(court)) + '",\n'
            content += '    ],\n'
            content += '    "categories": [' + '\n'
            for category in self.categories.true_values():
              content += "      '" + oneline(category) + "',\n"
            if self.categories['Other']:
              for category in self.other_categories.split(','):
                content += "      '" + escape_quotes(oneline(category.strip())) + "',\n"
            content += "    ],\n"
            content += "    'logic block variable': '" + self.interview_label + "',\n"
            content += "    'attachment block variable': '" + self.interview_label + "_attachment',\n"
            if hasattr(self, 'typical_role'):
              content += "    'typical role': '" + oneline(self.typical_role) + "',\n"
            content += "  })\n"
        elif self.type == 'modules':
            content += "modules:\n"
            for module in self.modules:
                content += " - " + str(module) + "\n"
        elif self.type == 'includes':
          content += "include:\n"
          for include in self.includes:
            content += "  - " + include + "\n"
        elif self.type == 'interstitial':
          if hasattr(self, 'comment'):
            content += 'comment: |\n'
            content += indent_by(self.comment, 2)
          if hasattr(self, 'id') and self.id:
            content += "id: " + self.id + "\n"
          else:
            without_bad_chars = varname(oneline(self.question_text))
            if len(without_bad_chars) == 0:
              # TODO(brycew): we can do better than meaningless text
              without_bad_chars = str(uuid.uuid4())
            content += "id: " + without_bad_chars + "\n"
          content += 'continue button field: ' + self.continue_button_field + "\n"
          content += "question: |\n"
          content += indent_by(self.question_text, 2)
          content += "subquestion: |\n"
          content += indent_by(self.subquestion_text, 2)
        elif self.type == "review" and len(self.parent_collections) > 0:
          if hasattr(self, 'id') and self.id:
              content += "id: " + self.id + "\n"
          else:
              content += "id: " + oneline(self.question_text) + "\n"
          if hasattr(self, 'event'):
              content += "event: " + self.event + "\n"
          content += "question: |\n"
          content += indent_by(self.question_text, 2)
          content += "subquestion: |\n"
          content += indent_by(self.subquestion_text, 2)
          content += "review: \n"
          for parent_coll in self.parent_collections:
            content += parent_coll.review_yaml() 
            content += '  - note: |\n      ------\n'
          for parent_coll in self.parent_collections:
            content += parent_coll.revisit_page()
            content += parent_coll.table_page()
        return content

class DAQuestionList(DAList):
  """This represents a list of DAQuestions."""
  def init(self, **kwargs):
    super().init(**kwargs)
    self.object_type = DAQuestion
    # self.auto_gather = False
    # self.gathered = True
    # self.is_mandatory = False

  def all_fields_used(self):
    """This method is used to help us iteratively build a list of fields that have already been assigned to a screen/question
      in our wizarding process. It makes sure the fields aren't displayed to the wizard user on multiple screens.
      It prevents the formatter of the wizard from putting the same fields on two different screens."""
    fields = set()
    for question in self.elements:
      if hasattr(question,'field_list'):
        for field in question.field_list.elements:
          fields.add(field)
    return fields

class PlaygroundSection(object):
    def __init__(self, section='', project='default'):
        if docassemble.base.functions.this_thread.current_info['user']['is_anonymous']:
            raise DAError("Users must be logged in to create Playground objects")
        self.user_id = docassemble.base.functions.this_thread.current_info['user']['theid']
        self.current_info = docassemble.base.functions.this_thread.current_info
        self.section = section
        self.project = project
        self._update_file_list()
    def get_area(self):
        return SavedFile(self.user_id, fix=True, section='playground' + self.section)
    def _update_file_list(self):
        the_directory = directory_for(self.get_area(), self.project)
        self.file_list = sorted([f for f in os.listdir(the_directory) if f != '.placeholder' and os.path.isfile(os.path.join(the_directory, f))])
    def image_file_list(self):
        out_list = list()
        for the_file in self.file_list:
            _extension, mimetype = get_ext_and_mimetype(the_file)
            if re.search(r'^image', mimetype):
                out_list.append(the_file)
        return out_list
    def reduced_file_list(self):
        lower_list = [f.lower() for f in self.file_list]
        out_list = [f for f in self.file_list if os.path.splitext(f)[1].lower() in ['.md', '.pdf', '.docx'] or os.path.splitext(f)[0].lower() + '.md' not in lower_list]
        return out_list
    def get_file(self, filename):
        return os.path.join(directory_for(self.get_area(), self.project), filename)
    def file_exists(self, filename):
        path = self.get_file(filename)
        if os.path.isfile(path):
            return True
        return False
    def delete_file(self, filename):
        area = self.get_area()
        the_filename = filename
        if self.project != 'default':
            the_filename = os.path.join(self.project, the_filename)
        area.delete_file(the_filename)
    def read_file(self, filename):
        path = self.get_file(filename)
        if path is None:
            return None
        with open(path, 'rU', encoding='utf-8') as fp:
            content = fp.read()
            return content
        return None
    def write_file(self, filename, content, binary=False):
        area = self.get_area()
        the_directory = directory_for(area, self.project)
        path = os.path.join(the_directory, filename)
        if binary:
            with open(path, 'wb') as ifile:
                ifile.write(content)
        else:
            with open(path, 'w', encoding='utf-8') as ifile:
                ifile.write(content)
        area.finalize()
    def commit(self):
        self.get_area().finalize()
    def copy_from(self, from_file, filename=None):
        if filename is None:
            filename = os.path.basename(from_file)
        to_path = self.get_file(filename)
        shutil.copy2(from_file, to_path)
        self.get_area().finalize()
        return filename
    def is_fillable_docx(self, filename):
        extension, _mimetype = get_ext_and_mimetype(filename)
        if extension != "docx":
            return False
        if not self.file_exists(filename):
            return False
        path = self.get_file(filename)
        result_file = word_to_markdown(path, 'docx')
        if result_file is None:
            return False
        with open(result_file.name, 'rU', encoding='utf-8') as fp:
            result = fp.read()
        fields = set()
        for variable in re.findall(r'{{ *([^\} ]+) *}}', result):
            fields.add(docx_variable_fix(variable))
        for variable in re.findall(r'{%[a-z]* for [A-Za-z\_][A-Za-z0-9\_]* in *([^\} ]+) *%}', result):
            fields.add(docx_variable_fix(variable))
        if len(fields):
            return True
        return False
    def is_markdown(self, filename):
        extension, _mimetype = get_ext_and_mimetype(filename)
        if extension == "md":
            return True
        return False
    def is_pdf(self, filename):
        extension, mimetype = get_ext_and_mimetype(filename)
        if extension == "pdf":
            return True
        return False
    def get_fields(self, filename):
        return docassemble.base.pdftk.read_fields(self.get_file(filename))
    def convert_file_to_md(self, filename, convert_variables=True):
        extension, mimetype = get_ext_and_mimetype(filename)
        if (mimetype and mimetype in convertible_mimetypes):
            the_format = convertible_mimetypes[mimetype]
        elif extension and extension in convertible_extensions:
            the_format = convertible_extensions[extension]
        else:
            return None
        if not self.file_exists(filename):
            return None
        path = self.get_file(filename)
        temp_file = word_to_markdown(path, the_format)
        if temp_file is None:
            return None
        out_filename = os.path.splitext(filename)[0] + '.md'
        if convert_variables:
            with open(temp_file.name, 'rU', encoding='utf-8') as fp:
                self.write_file(out_filename, replace_square_brackets.sub(fix_variable_name, fp.read()))
        else:
            shutil.copyfile(temp_file.name, self.get_file(out_filename))
        return out_filename
    def variables_from_file(self, filename):
        content = self.read_file(filename)
        if content is None:
            return None
        return Playground().variables_from(content)

class Playground(PlaygroundSection):
    def __init__(self):
        return super().__init__()
    def interview_url(self, filename):
        return docassemble.base.functions.url_of('interview', i='docassemble.playground' + str(self.user_id) + project_name(self.project) + ":" + filename)
    def write_package(self, pkgname, info):
        the_yaml = yaml.safe_dump(info, default_flow_style=False, default_style = '|')
        pg_packages = PlaygroundSection('packages')
        pg_packages.write_file(pkgname, the_yaml)
    def get_package_as_zip(self, pkgname):
        pg_packages = PlaygroundSection('packages')
        content = pg_packages.read_file(pkgname)
        if content is None:
            raise Exception("package " + str(pkgname) + " not found")
        info = yaml.load(content, Loader=yaml.FullLoader)
        author_info = dict()
        author_info['author name'] = self.current_info['user']['firstname'] + " " + self.current_info['user']['lastname']
        author_info['author email'] = self.current_info['user']['email']
        author_info['author name and email'] = author_info['author name'] + ", " + author_info['author email']
        author_info['first name'] = self.current_info['user']['firstname']
        author_info['last name'] = self.current_info['user']['lastname']
        author_info['id'] = self.user_id
        if self.current_info['user']['timezone']:
            the_timezone = self.current_info['user']['timezone']
        else:
            the_timezone = docassemble.base.functions.get_default_timezone()
        zip_file = make_package_zip(pkgname, info, author_info, the_timezone)
        file_number, extension, mimetype = docassemble.base.parse.save_numbered_file('docassemble-' + str(pkgname) + '.zip', zip_file.name)
        return file_number
    def variables_from(self, content):
        the_directory = directory_for(self.get_area(), self.project)
        interview_source = docassemble.base.parse.InterviewSourceString(content=content, directory=the_directory, path="docassemble.playground" + str(self.user_id) + project_name(self.project) + ":_temp.yml", package='docassemble.playground' + str(self.user_id) + project_name(self.project), testing=True)
        interview = interview_source.get_interview()
        temp_current_info = copy.deepcopy(self.current_info)
        temp_current_info['yaml_filename'] = "docassemble.playground" + str(self.user_id) + project_name(self.project) + ":_temp.yml"
        interview_status = docassemble.base.parse.InterviewStatus(current_info=temp_current_info)
        user_dict = docassemble.base.parse.get_initial_dict()
        user_dict['_internal']['starttime'] = datetime.datetime.utcnow()
        user_dict['_internal']['modtime'] = datetime.datetime.utcnow()
        try:
            interview.assemble(user_dict, interview_status)
        except Exception as errmess:
            error_message = str(errmess)
            error_type = type(errmess)
            #logmessage("Failed assembly with error type " + str(error_type) + " and message: " + error_message)
        functions = set()
        modules = set()
        classes = set()
        fields_used = set()
        names_used = set()
        names_used.update(interview.names_used)
        area = SavedFile(self.user_id, fix=True, section='playgroundmodules')
        the_directory = directory_for(area, self.project)
        avail_modules = set([re.sub(r'.py$', '', f) for f in os.listdir(the_directory) if os.path.isfile(os.path.join(the_directory, f))])
        for question in interview.questions_list:
            names_used.update(question.mako_names)
            names_used.update(question.names_used)
            names_used.update(question.fields_used)
            fields_used.update(question.fields_used)
        for val in interview.questions:
            names_used.add(val)
            fields_used.add(val)
        for val in user_dict:
            if type(user_dict[val]) is types.FunctionType:
                functions.add(val)
            elif type(user_dict[val]) is TypeType or type(user_dict[val]) is types.ClassType:
                classes.add(val)
            elif type(user_dict[val]) is types.ModuleType:
                modules.add(val)
        for val in docassemble.base.functions.pickleable_objects(user_dict):
            names_used.add(val)
        for var in ['_internal']:
            names_used.discard(var)
        names_used = names_used.difference( functions | classes | modules | avail_modules )
        undefined_names = names_used.difference(fields_used | always_defined )
        for var in ['_internal']:
            undefined_names.discard(var)
        names_used = names_used.difference( undefined_names )
        all_names = names_used | undefined_names | fields_used
        all_names_reduced = all_names.difference( set(['url_args']) )
        return dict(names_used=names_used, undefined_names=undefined_names, fields_used=fields_used, all_names=all_names, all_names_reduced=all_names_reduced)

def fix_id(string):
    return re.sub(r'[\W_]+', ' ', string).strip()

def fix_variable_name(match):
    var_name = match.group(1)
    var_name = end_spaces.sub(r'', var_name)
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    if len(var_name):
        return r'${ ' + var_name + ' }'
    return r''

def indent_by(text, num):
    if not text:
        return ""
    return (" " * num) + re.sub(r'\r*\n', "\n" + (" " * num), text).rstrip() + "\n"

def varname(var_name):
    var_name = var_name.strip() 
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    return var_name

def oneline(text):
    '''Replaces all new line characters with a space'''
    text = newlines.sub(r' ', text)
    return text

def escape_quotes(text):
    """Escape both single and double quotes in strings"""
    return text.replace('"', '\\"').replace("'", "\\'")

def to_yaml_file(text):
    text = varname(text)
    text = re.sub(r'\..*', r'', text)
    text = re.sub(r'[^A-Za-z0-9]+', r'_', text)
    return text + '.yml'

def base_name(filename):
    return os.path.splitext(filename)[0]

def repr_str(text):
    return remove_u.sub(r'', repr(text))

def docx_variable_fix(variable):
    variable = re.sub(r'\\', '', variable)
    variable = re.sub(r'^([A-Za-z\_][A-Za-z\_0-9]*).*', r'\1', variable)
    return variable

def directory_for(area, current_project):
    if current_project == 'default':
        return area.directory
    else:
        return os.path.join(area.directory, current_project)

def project_name(name):
    return '' if name == 'default' else name


def get_pdf_fields(the_file):
  """Patch over https://github.com/jhpyle/docassemble/blob/10507a53d293c30ff05efcca6fa25f6d0ded0c93/docassemble_base/docassemble/base/core.py#L4098"""
  results = list()
  import docassemble.base.pdftk
  all_fields = docassemble.base.pdftk.read_fields(the_file.path())
  if all_fields is None:
    return None
  for item in docassemble.base.pdftk.read_fields(the_file.path()):
    the_type = re.sub(r'[^/A-Za-z]', '', str(item[4]))
    if the_type == 'None':
      the_type = None
    result = (item[0], '' if item[1] == 'something' else item[1], item[2], item[3], the_type, item[5])
    results.append(result)
  return results

def get_fields(the_file):
  """Get the list of fields needed inside a template file (PDF or Docx Jinja
  tags). This will include attributes referenced. Assumes a file that
  has a valid and exiting filepath."""
  if isinstance(the_file, DAFileList):
    if the_file[0].mimetype == 'application/pdf':
      return [field[0] for field in the_file[0].get_pdf_fields()]
  else:
    if the_file.mimetype == 'application/pdf':
      return [field[0] for field in the_file.get_pdf_fields()]

  docx_data = docx2python( the_file.path() )  # Will error with invalid value
  text = docx_data.text
  return get_docx_variables( text )


def get_docx_variables( text:str )->set:
  """
  Given the string from a docx file with fairly simple
  code), returns a list of everything that looks like a jinja variable in the string.

  Limits: some attributes and methods might not be designed to be directly
  assigned in docassemble. Methods are stripped, but you may be left with
  something you didn't intend. This is only going to help reach a draft interview.

  Special handling for methods that look like they belong to Individual/Address classes.
  """
  #   Can be easily tested in a repl using the libs keyword and re
  minimally_filtered = set()
  for possible_variable in re.findall(r'{{ *([^\} ]+) *}}', text): # Simple single variable use
    minimally_filtered.add( possible_variable )
  # Variables in the second parts of for loops (allow paragraph and whitespace flags)
  for possible_variable in re.findall(r'\{%[^ \t]* +for [A-Za-z\_][A-Za-z0-9\_]* in ([^\} ]+) +[^ \t]*%}', text):
    minimally_filtered.add( possible_variable )
  # Variables in very simple `if` statements (allow paragraph and whitespace flags)
  for possible_variable in re.findall(r'{%[^ \t]* +if ([^\} ]+) +[^ \t]*%}', text):
    minimally_filtered.add( possible_variable )

  fields = set()

  for possible_var in minimally_filtered:
    # If no suffix exists, it's just the whole string
    prefix = re.findall(r'([^.]*)(?:\..+)*', possible_var)
    if not prefix[0]: continue  # This should never occur as they're all strings
    prefix_with_key = prefix[0]  # might have brackets

    prefix_root = re.sub(r'\[.+\]', '', prefix_with_key)  # no brackets
    # Filter out non-identifiers (invalid variable names), like functions
    if not prefix_root.isidentifier(): continue
    # Filter out keywords like `in`
    if keyword.iskeyword( prefix_root ): continue

    # Help gathering actual address as an attribute when document says something
    # like address.block()
    if '.address' in possible_var:  # an address
      if '.address.county' in possible_var:  # a county is special
        fields.add( possible_var )
      else:  # all other addresses and methods on addresses (replaces .address_block() and .address.block())
        fields.add( re.sub(r'\.address.*', '.address.address', possible_var ))
      # fields.add( prefix_with_key ) # Can't recall who added or what was this supposed to do?
      # It will add an extra, erroneous entry of the object root, which usually doesn't
      # make sense for a docassemble question
      continue
      
    if '.mail_address' in possible_var:  # a mailing address
      if '.mail_address.county' in possible_var:  # a county is special
        fields.add( possible_var )
      else:  # all other mailing addresses (replaces .zip and such)
        fields.add( re.sub(r'\.mail_address.*', '.mail_address.address', possible_var ))
      continue

    if '.name' in possible_var:  # a name
      if '.name.text' in possible_var:  # Names for non-Individuals
        fields.add( possible_var )
      else:  # Names for Individuals
        fields.add( re.sub(r'\.name.*', '.name.first', possible_var ))
      continue

    # TODO: Put in a test here for some_list.familiar() and for some_list[0].familiar()

    # Remove any methods from the end of the variable
    methods_removed = re.sub( r'(.*)\..*\(.*\)', '\\1', possible_var )
    fields.add( methods_removed )

  return fields


########################################################
# Map names code

# TODO: map_names is deprecated but old code depends on it. This is temporary shim
def map_names(label, document_type="pdf", reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
              custom_people_plurals_map=custom_values.people_plurals_map,
              reserved_prefixes=generator_constants.RESERVED_PREFIXES,
              undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
              reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS,
              reserved_pluralizers_map = generator_constants.RESERVED_PLURALIZERS_MAP,
              reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
  return map_raw_to_final_display(label, document_type=document_type,
              reserved_whole_words=reserved_whole_words,
              custom_people_plurals_map=custom_people_plurals_map,
              reserved_prefixes=reserved_prefixes,
              undefined_person_prefixes=undefined_person_prefixes,
              reserved_var_plurals=reserved_var_plurals,
              reserved_pluralizers_map = reserved_pluralizers_map,
              reserved_suffixes_map=reserved_suffixes_map)
  
def map_raw_to_final_display(label, document_type="pdf", reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
              custom_people_plurals_map=custom_values.people_plurals_map,
              reserved_prefixes=generator_constants.RESERVED_PREFIXES,
              undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
              reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS,
              reserved_pluralizers_map = generator_constants.RESERVED_PLURALIZERS_MAP,
              reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
  """For a given set of specific cases, transform a
  PDF field name into a standardized object name
  that will be the value for the attachment field."""
  if document_type.lower() == "docx":
    return label # don't transform DOCX variables

  # Turn spaces into `_`, strip non identifier characters
  label = varname(label)

  # Remove multiple appearance indicator, e.g. '__4' of 'users__4'
  label = remove_multiple_appearance_indicator(label)

  if (label in reserved_whole_words
   or label in reserved_var_plurals
   or label in undefined_person_prefixes
   or label in custom_people_plurals_map.values()):
     return label

  # Break up label into its parts: prefix, digit, the rest
  all_prefixes = reserved_prefixes + list(custom_people_plurals_map.values())
  label_groups = get_reserved_label_parts(all_prefixes, label)

  # If no matches to automateable labels were found,
  # just use the label as it is
  if label_groups is None or label_groups[1] == '':
    return label

  prefix = label_groups[1]
  # Map prefix to an adjusted version
  # At the moment, turn any singulars into plurals if needed, e.g. 'user' into 'users'
  adjusted_prefix = reserved_pluralizers_map.get(prefix, prefix)
  adjusted_prefix = custom_people_plurals_map.get(prefix, adjusted_prefix)
  # With reserved plurals, we're always using an index
  # of the plural version of the prefix of the label
  if (adjusted_prefix in reserved_var_plurals
      or adjusted_prefix in custom_people_plurals_map.values()):
    digit = label_groups[2]
    if digit == '':
      index = '[0]'
    else:
      index = '[' + str(int(digit)-1) + ']'
  else:
    digit = ''
    index = ''
  
  # it's just a standalone, like "defendant", or it's a numbered singular
  # prefix, e.g. user3
  if label == prefix or label == prefix + digit:
    return adjusted_prefix + index # Return the pluralized standalone variable

  suffix = label_groups[3]
  # Avoid transforming arbitrary suffixes into attributes
  if not suffix in reserved_suffixes_map:
    return label  # return it as is

  # Get the mapped suffix attribute if present, else just use the same suffix
  suffix_as_attribute = reserved_suffixes_map.get(suffix, suffix)
  return "".join([adjusted_prefix, index, suffix_as_attribute])


def is_reserved_docx_label(label, docx_only_suffixes=generator_constants.DOCX_ONLY_SUFFIXES,
                           reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
                           undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
                           reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
                           reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
    '''Given a string, will return whether the string matches
    reserved variable names. `label` must be a string.'''
    if label in reserved_whole_words:
        return True

    # Everything before the first period and everything from the first period to the end
    label_parts = re.findall(r'([^.]*)(\..*)*', label)

    # test for existence (empty strings result in a tuple)
    if not label_parts[0]:
      return False
    # The prefix, ensuring no key or index
    # Not sure this handles keys/attributes
    prefix = re.sub(r'\[.+\]', '', label_parts[0][0])
    is_reserved = prefix in reserved_pluralizers_map.values() or prefix in undefined_person_prefixes

    if is_reserved:
      suffix = label_parts[0][1]
      if not suffix:  # If only the prefix
        return True
      # If the suffix is also reserved
      # Regex for finding all exact matches of docx suffixes
      docx_only_suffixes_regex = '^' + '$|^'.join(docx_only_suffixes) + '$'
      docx_suffixes_matches = re.findall(docx_only_suffixes_regex, suffix)
      if (suffix in reserved_suffixes_map.values()
          or len(docx_suffixes_matches) > 0):
        return True

    # For all other cases
    return False


# # TODO: Remove unused function
# def get_regex(reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS, reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
#     reserved_beginning_regex = r'(^' + '|'.join(reserved_var_plurals) + ')'

#     # Does the ending matching a reserved name?
#     # Note the ending list includes the . already
#     ending_reserved_regex = '(' + '|'.join(list(filter(None,reserved_suffixes_map.values()))).replace('(',r'\(').replace(')',r'\)').replace('.',r'\.')
#     ending_reserved_regex += '|' + '|'.join(docx_only_suffixes) + ')'

#     return reserved_beginning_regex + '(.*)' + ending_reserved_regex

############################
#  Identify reserved PDF labels
############################
def is_reserved_label(label, reserved_whole_words = generator_constants.RESERVED_WHOLE_WORDS, reserved_prefixes = generator_constants.RESERVED_PREFIXES, reserved_var_plurals = generator_constants.RESERVED_VAR_PLURALS, reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
  '''Given a PDF label, returns whether the label fully
    matches a reserved prefix or a reserved prefix with a
    reserved suffix'''

  # Get rid of all multi-appearance indicators, e.g. '__4' of 'user_name__4'
  # Doesn't matter if it's a first appearance or more
  label = remove_multiple_appearance_indicator(label)

  if label in reserved_whole_words:
    return True
  # For the sake of time, this is the fastest way to get around something being plural
  if label in reserved_var_plurals:
    return True

  # Break up label into its parts
  label_groups = get_reserved_label_parts(reserved_prefixes, label)
  # If no other matches to reserved prefixes were found
  if (label_groups is None or label_groups[1] == ''):
    return False
  # If there are no suffixes, just the reserved prefix
  suffix = label_groups[3]
  if (suffix == ""):
    return True

  return suffix in reserved_suffixes_map


############################
#  Label processing helper functions
############################
def remove_multiple_appearance_indicator(label: str) -> str:
    return re.sub(r'_{2,}\d+', '', label)

def substitute_suffix(label: str, display_suffixes: Dict[str, str]) -> str:
  """Map attachment/displayable attributes or methods into interview order
  attributes. For example, `.address()` will become `.address.address`"""
  for suffix in display_suffixes:
    match_regex = re.compile( '.*' + suffix )
    if re.match( match_regex, label ):
      sub_regex = re.compile( suffix )
      new_label = re.sub( sub_regex, display_suffixes[suffix], label )
      return new_label
  return label

def get_reserved_label_parts(prefixes:list, label:str):
  """
  Return an re.matches object for all matching variable names,
  like user1_something, etc.
  """
  return re.search(r"^(" + "|".join(prefixes) + ')(\d*)(.*)', label)

def process_custom_people(custom_people:list, fields:list, built_in_fields:list, people_suffixes:list = (generator_constants.PEOPLE_SUFFIXES + generator_constants.DOCX_ONLY_SUFFIXES) )->None:
  """
  Move fields from `fields` to `built_in_fields` list if the user
  indicated they are going to be treated as ALPeopleLists
  """
  # Iterate over DAFieldList 
  # If any fields match a custom person with a pre-handled suffix, remove them
  # from the list and add them to the list of built_in_fields_used
  delete_list = []
  fields_to_add = set()
  for field in fields:
    # Simpler case: PDF variables matching our naming rules
    new_potential_name = map_raw_to_final_display(field.variable, reserved_prefixes=custom_people)
    # If it's not already a DOCX-like variable and the new mapped name doesn't match old name
    if not ('[' in field.variable) and new_potential_name != field.variable:
      field.final_display_var = new_potential_name
      for person in custom_people:
        if field.final_display_var.startswith(person + "["):
          field.custom_trigger_gather = person + ".gather()"
      fields_to_add.add(field)
      delete_list.append(field) # Cannot mutate in place
    else:
      # check for possible DOCX match of prefix + suffix, w/ [index] removed
      matching_docx_test = r"^(" + "|".join(custom_people) + ")\[\d+\](" + ("|".join([suffix.replace(".","\.") for suffix in people_suffixes])) + ")$"
      log(matching_docx_test)
      if re.match(matching_docx_test, field.variable):
        for person in custom_people:
          if field.final_display_var.startswith(person + "["):
            field.custom_trigger_gather = person + ".gather()"
        delete_list.append(field)
        fields_to_add.add(field)

  for field in delete_list:
    fields.remove(field)

  for field in fields_to_add:
    built_in_fields.append(field)






def get_person_variables(fieldslist,
                         undefined_person_prefixes = generator_constants.UNDEFINED_PERSON_PREFIXES,
                         people_vars = generator_constants.PEOPLE_VARS,
                         people_suffixes = generator_constants.PEOPLE_SUFFIXES,
                         people_suffixes_map = generator_constants.PEOPLE_SUFFIXES_MAP,
                         reserved_person_pluralizers_map = generator_constants.RESERVED_PERSON_PLURALIZERS_MAP,
                         custom_only=False):
  """
  Identify the field names that appear to represent people in the list of
  string fields pulled from docx/PDF. Exclude people we know
  are singular Persons (such as trial_court).
  """
  people = set()
  for field in fieldslist:
    # fields are currently tuples for PDF and strings for docx
    if isinstance(field, tuple):
      # map_raw_to_final_display will only transform names that are built-in to the constants
      field_to_check = map_raw_to_final_display(field[0])
    else:
      field_to_check = field
    # Exact match
    if (field_to_check) in people_vars:
      people.add(field_to_check)
    elif (field_to_check) in undefined_person_prefixes:
      pass  # Do not ask how many there will be about a singluar person
    elif '[' in field_to_check or '.' in field_to_check:
      # Check for a valid Python identifier before brackets or .
      match_with_brackets_or_attribute = r"([A-Za-z_]\w*)((\[.*)|(\..*))"
      matches = re.match(match_with_brackets_or_attribute, field_to_check)
      if matches:
        if matches.groups()[0] in undefined_person_prefixes:
          # Ignore singular objects like trial_court
          pass
        # Is the name before attribute/index a predetermined person?  
        elif matches.groups()[0] in people_vars:
          people.add(matches.groups()[0])
        # Maybe this is the singular version of a person's name?
        elif matches.groups()[0] in reserved_person_pluralizers_map.keys():
          people.add(reserved_person_pluralizers_map[matches.groups()[0]])
        else:
          # This will be reached only for a DOCX and we decided to make
          # custom people all be plural. So we ALWAYS strip off the leading
          # index, like [0].name.first
          possible_suffix = re.sub('^\[\d+\]','',matches.groups()[1])
          # Look for suffixes normally associated with people like .name.first for a DOCX
          if possible_suffix in people_suffixes:
            people.add(matches.groups()[0]) 
    else:
      # If it's a PDF name that wasn't transformed by map_raw_to_final_display, do one last check
      # In this branch and all subbranches strip trailing numbers
      # regex to check for matching suffixes, and catch things like mail_address_address
      # instead of just _address_address, if the longer one matches
      match_pdf_person_suffixes = r"(.+?)(?:(" + "$)|(".join(people_suffixes_map.keys()) + "$))"
      matches = re.match(match_pdf_person_suffixes, field_to_check)
      if matches:
        if not matches.groups()[0] in undefined_person_prefixes:
          # Skip pre-defined but singular objects since they are not "people" that
          # need to turn into lists.
          # currently this is only trial_court
          people.add(re.sub(r"\d+$","",matches.groups()[0]))
  if custom_only:
    return people - set(people_vars)
  else:
    return people

def set_custom_people_map( people_var_names ):
  """Sets the map of custom people created by the developer."""
  for var_name in people_var_names:
    custom_values.people_plurals_map[ var_name ] = var_name
  return custom_values.people_plurals_map

def create_package_zip(pkgname: str, info: dict, author_info: dict, folders_and_files: dict, fileobj:DAFile=None)->DAFile:
  """
  Given a dictionary of lists, with the keys representing folders and the values
  representing a list of DAFiles, create a Python package with Docassemble conventions.
  info: (created by DAInterview.package_info()) 
    license
    author_name
    readme
    description
    url
    version
    dependencies
    // interview_files replaced with folders_and_files
    // template_files
    // module_files
    // static_files
  author_info:
    author name and email  
  folders_and_files:
    questions->list of DAFiles/DAFile-like objects
    templates
    modules
    static
    sources

  Strucure of a docassemble package:
  + docassemble-PKGNAME/
      LICENSE
      MANIFEST.in
      README.md
      setup.cfg
      setup.py
      +-------docassemble
          __init__.py
          +------PKGNAME
              __init__.py
              SOME_MODULE.py
              +------data
                  +------questions
                      README.md
                  +------sources
                      README.md  
                  +------static
                      README.md  
                  +------templates
                      README.md
  """
  pkgname = space_to_underscore(pkgname)
  if fileobj:
    zip_download = fileobj
  else: 
    zip_download = DAFile()
  pkg_path_prefix = "docassemble-" + pkgname
  pkg_path_init_prefix = os.path.join(pkg_path_prefix, "docassemble")
  pkg_path_deep_prefix = os.path.join(pkg_path_init_prefix, pkgname)
  pkg_path_data_prefix = os.path.join(pkg_path_deep_prefix, "data")
  pkg_path_questions_prefix = os.path.join(pkg_path_data_prefix,"questions")
  pkg_path_sources_prefix = os.path.join(pkg_path_data_prefix,"sources")
  pkg_path_static_prefix = os.path.join(pkg_path_data_prefix,"static")
  pkg_path_templates_prefix = os.path.join(pkg_path_data_prefix,"templates")

  zip_download.initialize(filename="docassemble-" + pkgname + ".zip")
  zip_obj = zipfile.ZipFile(zip_download.path(),'w')

  dependencies = ",".join(info['dependencies'])

  initpy = """\
try:
    __import__('pkg_resources').declare_namespace(__name__)
except ImportError:
    __path__ = __import__('pkgutil').extend_path(__path__, __name__)
"""
  licensetext = str(info['license'])
  if re.search(r'MIT License', licensetext):
    licensetext += '\n\nCopyright (c) ' + str(datetime.datetime.now().year) + ' ' + str(info.get('author_name', '')) + """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
  if info['readme'] and re.search(r'[A-Za-z]', info['readme']):
    readme = str(info['readme'])
  else:
    readme = '# docassemble.' + str(pkgname) + "\n\n" + info['description'] + "\n\n## Author\n\n" + author_info['author name and email'] + "\n\n"
  manifestin = """\
include README.md
"""
  setupcfg = """\
[metadata]
description-file = README.md
"""
  setuppy = """\
import os
import sys
from setuptools import setup, find_packages
from fnmatch import fnmatchcase
from distutils.util import convert_path
standard_exclude = ('*.pyc', '*~', '.*', '*.bak', '*.swp*')
standard_exclude_directories = ('.*', 'CVS', '_darcs', './build', './dist', 'EGG-INFO', '*.egg-info')
def find_package_data(where='.', package='', exclude=standard_exclude, exclude_directories=standard_exclude_directories):
    out = {}
    stack = [(convert_path(where), '', package)]
    while stack:
        where, prefix, package = stack.pop(0)
        for name in os.listdir(where):
            fn = os.path.join(where, name)
            if os.path.isdir(fn):
                bad_name = False
                for pattern in exclude_directories:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                if os.path.isfile(os.path.join(fn, '__init__.py')):
                    if not package:
                        new_package = name
                    else:
                        new_package = package + '.' + name
                        stack.append((fn, '', new_package))
                else:
                    stack.append((fn, prefix + name + '/', package))
            else:
                bad_name = False
                for pattern in exclude:
                    if (fnmatchcase(name, pattern)
                        or fn.lower() == pattern.lower()):
                        bad_name = True
                        break
                if bad_name:
                    continue
                out.setdefault(package, []).append(prefix+name)
    return out
"""
  setuppy += "setup(name='docassemble." + str(pkgname) + "',\n" + """\
      version=""" + repr(info.get('version', '')) + """,
      description=(""" + repr(info.get('description', '')) + """),
      long_description=""" + repr(readme) + """,
      long_description_content_type='text/markdown',
      author=""" + repr(info.get('author_name', '')) + """,
      author_email=""" + repr(info.get('author_email', '')) + """,
      license=""" + repr(info.get('license', '')) + """,
      url=""" + repr(info['url'] if info['url'] else 'https://docassemble.org') + """,
      packages=find_packages(),
      namespace_packages=['docassemble'],
      install_requires=[""" + dependencies + """],
      zip_safe=False,
      package_data=find_package_data(where='docassemble/""" + str(pkgname) + """/', package='docassemble.""" + str(pkgname) + """'),
     )
"""
  templatereadme = """\
# Template directory
If you want to use templates for document assembly, put them in this directory.
"""
  staticreadme = """\
# Static file directory
If you want to make files available in the web app, put them in
this directory.
"""
  sourcesreadme = """\
# Sources directory
This directory is used to store word translation files,
machine learning training files, and other source files.
"""
  templatesreadme = """\
# Template directory
This directory is used to store templates.
"""
  # Write the standard files
  zip_obj.writestr(os.path.join(pkg_path_prefix,"LICENSE"), licensetext)
  zip_obj.writestr(os.path.join(pkg_path_prefix,"MANIFEST.in"), manifestin)
  zip_obj.writestr(os.path.join(pkg_path_prefix,"README.md"), readme)
  zip_obj.writestr(os.path.join(pkg_path_prefix,"setup.cfg"), setupcfg)
  zip_obj.writestr(os.path.join(pkg_path_prefix,"setup.py"), setuppy)
  zip_obj.writestr(os.path.join(pkg_path_init_prefix,"__init__.py"), initpy)
  zip_obj.writestr(os.path.join(pkg_path_deep_prefix,"__init__.py"), ("__version__ = " + repr(info.get('version', '')) + "\n") )
  zip_obj.writestr(os.path.join(pkg_path_questions_prefix,"README.md"), templatereadme )
  zip_obj.writestr(os.path.join(pkg_path_sources_prefix,"README.md"), sourcesreadme )
  zip_obj.writestr(os.path.join(pkg_path_static_prefix,"README.md"), staticreadme)
  zip_obj.writestr(os.path.join(pkg_path_templates_prefix,"README.md"), templatesreadme)
  
  # Modules
  for file in folders_and_files.get('modules',[]):
    try:
      zip_obj.write(file.path(),os.path.join(pkg_path_deep_prefix, file.filename))
    except:
      log('Unable to add file ' + repr(file))        
  # Templates
  for file in folders_and_files.get('templates',[]):
    try:
      zip_obj.write(file.path(),os.path.join(pkg_path_templates_prefix, file.filename))
    except:
      log('Unable to add file ' + repr(file))
  # sources
  for file in folders_and_files.get('sources',[]):
    try:
      zip_obj.write(file.path(),os.path.join(pkg_path_sources_prefix, file.filename))
    except:
      log('Unable to add file ' + repr(file))
  # static
  for file in folders_and_files.get('static',[]):
    try:
      zip_obj.write(file.path(),os.path.join(pkg_path_static_prefix, file.filename))
    except:
      log('Unable to add file ' + repr(file))
  # questions
  for file in folders_and_files.get('questions',[]):
    try:
      zip_obj.write(file.path(),os.path.join(pkg_path_questions_prefix, file.filename))
    except:
      log('Unable to add file ' + repr(file))
  
  zip_obj.close()
  zip_download.commit()
  return zip_download
