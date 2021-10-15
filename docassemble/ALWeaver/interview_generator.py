import ast
import keyword
import os
import re
import uuid
from collections import defaultdict
from docx2python import docx2python
from docassemble.base.error import DAError
from docassemble.base.util import log, space_to_underscore, bold, DAObject, DAList, DAFile, DAFileList, path_and_mimetype, user_info
import docassemble.base.functions
import docassemble.base.parse
import docassemble.base.pdftk
from docassemble.base.core import DAEmpty
import datetime
import zipfile
import json
from typing import Any, Dict, List, Tuple, Union #, Set
from .generator_constants import generator_constants
from .custom_values import custom_values
import ruamel.yaml as yaml
import mako.template
import mako.runtime
from pdfminer.pdftypes import PDFObjRef, resolve1

mako.runtime.UNDEFINED = DAEmpty()


TypeType = type(type(None))

__all__ = ['ParsingException', 'indent_by', 'varname', 'DAField', 'DAFieldList', \
           'DAQuestion', 'DAInterview', 'to_yaml_file', \
           'base_name', 'escape_quotes', 'oneline', 'DAQuestionList', 'map_raw_to_final_display', \
           'is_reserved_label', 'attachment_download_html', \
           'get_fields', 'get_pdf_fields', 'is_reserved_docx_label','get_character_limit', \
           'create_package_zip', 'remove_multiple_appearance_indicator', \
           'get_person_variables', 'get_court_choices',\
           'process_custom_people', 'set_custom_people_map',\
           'fix_id','DABlock', 'DABlockList','mako_indent',\
           'using_string', 'pdf_field_type_str', \
           'bad_name_reason', 'mako_local_import_str']

always_defined = set(["False", "None", "True", "dict", "i", "list", "menu_items", "multi_user", "role", "role_event", "role_needed", "speak_text", "track_location", "url_args", "x", "nav", "PY2", "string_types"])
replace_square_brackets = re.compile(r'\\\[ *([^\\]+)\\\]')
end_spaces = re.compile(r' +$')
spaces = re.compile(r'[ \n]+')
invalid_var_characters = re.compile(r'[^A-Za-z0-9_]+')
digit_start = re.compile(r'^[0-9]+')
newlines = re.compile(r'\n')
remove_u = re.compile(r'^u')

class ParsingException(Exception):
  """Throws an error if we can't understand the labels somehow, so we can tell the user"""
  def __init__(self, message:str, description:str=None, url:str=None):
    self.main_issue = message
    self.description = description
    self.url = url

    super().__init__('main_issue: {}, description: {}, url: {}'.format(message, description, url))
                     
  def __reduce__(self):
    return (ParsingException, (self.main_issue, self.description, self.url))

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

class DABlock(DAObject):
  """
  A Block in a Docassemble interview YAML file.
  """
  template_key:str
  data:Dict[str,any]

  def source(self, template_string:str, imports:list=["from docassemble.ALWeaver.interview_generator import fix_id, varname, indent_by, mako_indent, using_string"])->str:
    """
    Return a string representing a YAML "document" (block), provided a string
    representing a Mako template. Optional: provide list of imports.
    """
    mako.runtime.UNDEFINED = DAEmpty()
    # Ensure we weren't passed an empty list of imports NOTE: is this important?
    if not imports:
      imports = ["from docassemble.ALWeaver.interview_generator import fix_id, varname, indent_by, mako_indent, using_string"]
    template = mako.template.Template(template_string, imports=imports)
    return template.render(**self.data)

class DABlockList(DAList):
  """
  This represents a list of DABlocks representing seperate YAML "documents"
  (blocks) in a Docassemble interview file
  """
  def init(self, *pargs, **kwargs):
    super().init(*pargs, **kwargs)
    self.object_type = DABlock  

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

class DAInterview(DAObject):
    """ 
    This class represents the final YAML output. It has a method to output
    to a string.

    It is designed to load and store a list of Mako templates representing each
    block type from a YAML file.
    """
    templates:Dict[str,str]
    template_path:str # Like: docassemble.ALWeaver:data/sources/interview_structure.yml
    blocks:DABlockList
    questions:DAQuestionList # is this used?

    def init(self, *pargs, **kwargs):
        super().init(*pargs, **kwargs)
        self.blocks = DABlockList(auto_gather=False, gathered=True, is_mandatory=False)
        self.questions = DAQuestionList(auto_gather=False, gathered=True, is_mandatory=False)

    def package_info(self, dependencies:List[str]=None) -> Dict[str, Any]:
        assembly_line_dep = 'docassemble.AssemblyLine'
        if dependencies is None:
            dependencies = [assembly_line_dep, 'docassemble.ALMassachusetts', 'docassemble.MassAccess']
        elif assembly_line_dep not in dependencies:
            dependencies.append(assembly_line_dep)

        info = dict()
        for field in ['interview_files', 'template_files', 'module_files', 'static_files']:
            if field not in info:
                info[field] = list()
        info['dependencies'] = dependencies
        info['author_name'] = ""                
        info['readme'] = ""
        info['description'] = self.title
        info['version'] = "1.0"
        info['license'] = "The MIT License"
        info['url'] = "https://courtformsonline.org"
        return info

    def source(self)->str:
        """
        Render and return the source of all blocks in the interview as a YAML string.
        """
        if getattr(self, 'template_path'):
          self._load_templates(self.template_path)
        else:
          self._load_templates("docassemble.ALWeaver:data/sources/interview_structure.yml")
        text = ""
        for block in self.blocks + self.questions.elements:
          text += "---\n"
          imports = self.templates.get('mako template imports',[])
          local_imports = self.templates.get('mako template local imports',[])
          formatted_local_imports = [ mako_local_import_str(user_info().package, import_key, local_imports[import_key]) for import_key in local_imports ]
          imports = imports + formatted_local_imports
          text += block.source(self.templates.get(block.template_key), imports=imports)
        return text

    def _load_templates(self, template_path:str)->None:
        """
        Load YAML file with Mako templates into the templates attribute.
        Overwrites any existing templates.
        """
        path = path_and_mimetype(template_path)[0]
        with open(path) as f:
          contents = f.read()
        self.templates = list(yaml.safe_load_all(contents))[0] # Take the first YAML "document"

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
    self.variable_name_guess = variable_name_guess

    if self.variable.endswith('_date'):
      self.field_type_guess = 'date'
      self.variable_name_guess = f"Date of {variable_name_guess[:-5]}"
    elif self.variable.endswith('_amount'):
        self.field_type_guess = 'currency'
    elif self.variable.endswith('_value'):
        self.field_type_guess = 'currency'
    elif self.variable.endswith('.signature'):
      self.field_type_guess = "signature"
    else:
      self.field_type_guess = 'text'

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
    self.maxlength = get_character_limit(pdf_field_tuple)
    self.variable_name_guess = variable_name_guess

    if self.variable.endswith('_date'):
        self.field_type_guess = 'date'
        self.variable_name_guess = 'Date of ' + self.variable[:-5].replace('_', ' ')
    elif self.variable.endswith('_yes') or self.variable.endswith('_no'):
        self.field_type_guess = 'yesno'
        name_no_suffix = self.variable[:-3] if self.variable.endswith('_no') else self.variable[:-4]
        self.variable_name_guess = name_no_suffix.replace('_', ' ').capitalize()
    elif pdf_field_tuple[4] == '/Btn':
        self.field_type_guess = 'yesno'
    elif pdf_field_tuple[4] == "/Sig":
        self.field_type_guess = "signature"
    elif self.maxlength > 100:
        self.field_type_guess = 'area'
    elif self.variable.endswith('_amount'):
        self.field_type_guess = 'currency'
    elif self.variable.endswith('_value'):
        self.field_type_guess = 'currency'
    else:
        self.field_type_guess = 'text'
    
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
      return "yesno: {}".format(settable_version)
    elif self.field_type == 'yesnomaybe':
      return "yesnomaybe: {}".format(settable_version)
    else:
      return ""

  def _maxlength_str(self) -> str:
    if hasattr(self, 'maxlength') and self.maxlength and not (hasattr(self, 'send_to_addendum') and self.send_to_addendum):
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
    elif self.field_type == 'multiple choice radio':
      content += "    input type: radio\n"
      content += "    choices:\n"
      for choice in self.choices.splitlines():
        content += f"      - {choice}\n"
    elif self.field_type == 'multiple choice checkboxes':
      content += "    datatype: checkboxes\n"
      content += "    choices:\n"
      for choice in self.choices.splitlines():
        content += f"      - {choice}\n"        
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
    
    return content.rstrip('\n')

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

  def attachment_yaml(self, attachment_name=None):
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
      return content.rstrip('\n')

    # Handle multiple indicators
    format_str = '      - "{}": '
    if hasattr(self, 'field_type') and self.field_type == 'date':
      format_str += '${{ ' + self.variable.format() + ' }}\n'
    elif hasattr(self, 'field_type') and self.field_type == 'currency':
      format_str += '${{ currency(' + self.variable + ') }}\n'
    elif hasattr(self, 'field_type') and self.field_type == 'number':
      format_str += r'${{ "{{:,.2f}}".format(' + self.variable + ') }}\n' 
    elif self.field_type_guess == 'signature': 
      if self.final_display_var.endswith('].signature'): # This is an ALIndividual
        # We don't need a comment with this more explanatory method name
        format_str += '${{ ' + self.final_display_var + '_if_final(i) }}\n'
      else: # this is less common, but not something we should break
        comment = "      # It's a signature: test which file version this is; leave empty unless it's the final version)\n"
        format_str = comment + format_str + '${{ ' + self.final_display_var + " if i == 'final' else '' }}\n"
    else: # normal text field
      if hasattr(self, 'send_to_addendum') and self.send_to_addendum and attachment_name:
        format_str += '${{' + attachment_name + '.safe_value("' + self.final_display_var + '")}}\n'
      else:        
        format_str += '${{ ' + self.final_display_var + ' }}\n'

    content = ''
    for raw_name in self.raw_field_names:
      content += format_str.format(raw_name)
    
    return content.rstrip('\n')
  
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
      'label': "On-screen label",
      'field': 'fields[' + str(index) + '].label',
      'default': self.variable_name_guess
    })
    field_questions.append({
      'label': "Field Type",
      'field': f'fields[{index}].field_type',
      'choices': ['text', 'area', 'yesno', 'integer', 'number', 'currency', 'date', 'email','multiple choice radio','multiple choice checkboxes'], 
      'default': self.field_type_guess if hasattr(self, 'field_type_guess') else None
    }) 
    field_questions.append({    
      'label': 'Options (one per line)',
      'field': f'fields[{index}].choices',
      'datatype': 'area',
      'js show if': f"val('fields[{index}].field_type') === 'multiple choice radio' || val('fields[{index}].field_type') === 'multiple choice checkboxes'",
      'hint': "Like 'Descriptive name: key_name', or just 'Descriptive name'",
    })
    field_questions.append({
      'label': "Send overflow text to addendum",
      'field': f'fields[{index}].send_to_addendum',
      'datatype': 'yesno',
      'show if': {'code': f'hasattr(fields[{index}], "maxlength")'},
      'help': "Check the box to send text that doesn't fit in the PDF to an additional page, instead of limiting the input length."
    })
    return field_questions

  def trigger_gather(self,
                     custom_people_plurals_map=custom_values.people_plurals_map,
                     reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
                     undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
                     reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP):
    """Turn the docassemble variable string into an expression
    that makes DA ask a question for it. This is mostly
    calling `gather()` for lists"""
    GATHER_CALL = '.gather()'
    if self.final_display_var in reserved_whole_words:
      return self.final_display_var

    if (self.final_display_var in reserved_pluralizers_map.values()
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
      elif first_attribute == '.address' or first_attribute == '.mailing_address':
        return var_parts[0][0] + first_attribute + '.address'
      else:
        return var_parts[0][0] + first_attribute
    else:
      return self.final_display_var

  def get_settable_var(self, 
      display_to_settable_suffix=generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX):
    return substitute_suffix(self.final_display_var, display_to_settable_suffix)
  
  def _get_attributes(self, full_display_map=generator_constants.FULL_DISPLAY,
      primitive_pluralizer=generator_constants.RESERVED_PRIMITIVE_PLURALIZERS_MAP):
    """Returns attributes of this DAField, notably without the leading "prefix", or object name
    * the plain attribute, not ParentCollection, but the direct attribute of the ParentCollection
    * the "full display", an expression that shows the whole attribute in human readable form
    * an expression that causes DA to set to this field
    
    For example: the DAField `user[0].address.zip` would return ('address', 'address.block()', 'address.address')
    """
    label_parts = re.findall(r'([^.]*)(\..*)*', self.get_settable_var())

    prefix_with_index = label_parts[0][0] 
    prefix = re.sub(r'\[.+\]', '', prefix_with_index)
    settable_attribute = label_parts[0][1].lstrip('.')
    if prefix in primitive_pluralizer.keys():
      # It's just a primitive (either by itself or in a list). I.e. docket_numbers
      settable_attribute = ''
      plain_att = ''
      full_display_att = ''
    else:
      if settable_attribute == '' or settable_attribute == 'name':
        settable_attribute = 'name.first'
      if settable_attribute == 'address' or settable_attribute == 'mailing_address':
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
        if plain_att:
          self.attribute_map[plain_att] = (disp_att, settable_att)

  def table_page(self) -> str:
    # TODO: migrate to Mako format
    if self.var_type != 'list':
      return ''
    content = """table: {var_name}.table
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
      all_columns += '  - {0}: |\n'.format(att.capitalize().replace('_', ' '))
      all_columns += '      row_item.{0} if defined("row_item.{1}") else ""\n'.format( disp_and_set[0], disp_and_set[1])
      settable_list += '  - {}\n'.format(disp_and_set[1])
    if len(self.attribute_map) == 0:
      all_columns += '  - Name: |\n'
      all_columns += '      row_item\n'
      settable_list += '  True\n'
    return content.format(var_name=self.var_name, all_columns=all_columns.rstrip('\n'), settable_list=settable_list.rstrip('\n'))

  def review_yaml(self): 
    """Generate the yaml entry for this object in the review screen list"""
    if self.var_type == 'list':
      edit_attribute = self.var_name + '.revisit'
    else:
      edit_attribute = self.var_name
      
    content = '  - Edit: ' + edit_attribute + "\n"
    content += '    button: |\n'
        
    if self.var_type == 'list': 
      content += indent_by(bold(self.var_name.capitalize().replace('_', ' ')), 6) + '\n'
      content += indent_by("% for item in {}:".format(self.var_name), 6)
      content += indent_by("* ${ item }", 8)
      content += indent_by("% endfor", 6)
      return content.rstrip('\n')
    
    if self.var_type == 'object':
      content += indent_by(bold(self.var_name), 6) + '\n'
      for att, disp_set in self.attribute_map.items():
        content += indent_by('% if defined("{}.{}"):'.format(self.var_name, disp_set[1]), 6)
        content += indent_by('* {}: ${{ {}.{} }}'.format(att, self.var_name, disp_set[0]), 6)
        content += indent_by('% endif', 6)
      return content.rstrip('\n')
    
    return content + self.fields[0].review_viewing().rstrip('\n')


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
    
class DAQuestion(DABlock):
  """
  Special DABlock that you can iteratively build in Assembly Line Weaver.

  Defaults to using the 'question' template and adds "field_list" attribute.
  """
  field_list:DAFieldList
  
  def init(self, *pargs, **kwargs):
    super().init(*pargs, **kwargs)
    self.template_key = 'question'
    self.field_list = DAFieldList()

  def source(self, template_string:str, imports:list=["from docassemble.ALWeaver.interview_generator import fix_id, varname, indent_by, mako_indent"])->str:
    """
    Return a string representing a YAML "document" (block), provided a string
    representing a Mako template. Optional: provide list of imports.
    """
    mako.runtime.UNDEFINED = DAEmpty()
    template = mako.template.Template(template_string, imports=imports)
    data = {
      "block_id": self.id if hasattr(self, 'id') else None,
      "event": self.event if hasattr(self, 'event') else None,
      "continue_button_field": varname(self.question_text) if self.needs_continue_button_field else None,
      "question_text": self.question_text,
      "subquestion_text": self.subquestion_text,
      "field_list": self.field_list
    }
    return template.render(**data)

def fix_id(string:str)->str:
    if string and isinstance(string, str):
      return re.sub(r'[\W_]+', ' ', string).strip()
    else:
      return str(uuid.uuid4())

def fix_variable_name(match)->str:
    var_name = match.group(1)
    var_name = end_spaces.sub(r'', var_name)
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    if len(var_name):
        return r'${ ' + var_name + ' }'
    return r''

def indent_by(text:str, num:int)->str:
    if not text:
        return ""
    return (" " * num) + re.sub(r'\r*\n', "\n" + (" " * num), text).rstrip() + "\n"

def mako_indent(text:str, num:int)->str:
  """
  Like indent_by but removes extra newline
  """
  if not text:
      return ""
  return (" " * num) + re.sub(r'\r*\n', "\n" + (" " * num), text).rstrip()

def mako_local_import_str(package_name:str, key:str, imports:List[str])->str:
  """
  Create an import string for mako template from the output_patterns.yml file, like
  `from docassemble.playground1.interview_generator import mako_indent, varname`
  """
  return 'from ' + package_name + '.' + key + ' import ' + ",".join(imports)

def varname(var_name:str)->str:
    if var_name:
      var_name = var_name.strip() 
      var_name = spaces.sub(r'_', var_name)
      var_name = invalid_var_characters.sub(r'', var_name)
      var_name = digit_start.sub(r'', var_name)
      return var_name
    return var_name

def oneline(text:str)->str:
    '''Replaces all new line characters with a space'''
    if text:
      return newlines.sub(r' ', text)
    return ''

def escape_quotes(text:str)->str:
    """Escape both single and double quotes in strings"""
    return text.replace('"', '\\"').replace("'", "\\'")

def to_yaml_file(text:str)->str:
    text = varname(text)
    text = re.sub(r'\..*', r'', text)
    text = re.sub(r'[^A-Za-z0-9]+', r'_', text)
    return text + '.yml'

def base_name(filename:str)->str:
    return os.path.splitext(filename)[0]

def repr_str(text:str)->str:
    return remove_u.sub(r'', repr(text))

def docx_variable_fix(variable:str)->str:
    variable = re.sub(r'\\', '', variable)
    variable = re.sub(r'^([A-Za-z\_][A-Za-z\_0-9]*).*', r'\1', variable)
    return variable

def get_pdf_fields(the_file):
  """Patch over https://github.com/jhpyle/docassemble/blob/10507a53d293c30ff05efcca6fa25f6d0ded0c93/docassemble_base/docassemble/base/core.py#L4098"""
  results = list()
  import docassemble.base.pdftk
  all_fields = docassemble.base.pdftk.read_fields(the_file.path())
  if all_fields is None:
    return None
  for field in all_fields:
    the_type = re.sub(r'[^/A-Za-z]', '', str(field[4]))
    if the_type == 'None':
      the_type = None
    result = (field[0], '' if field[1] == 'something' else field[1], field[2], field[3], the_type, field[5])
    results.append(tuple(map(shim_remove_pdf_obj_refs,result)))
  return results

def get_fields(the_file):
  """Get the list of fields needed inside a template file (PDF or Docx Jinja
  tags). This will include attributes referenced. Assumes a file that
  has a valid and exiting filepath."""
  if isinstance(the_file, DAFileList):
    if the_file[0].mimetype == 'application/pdf':
      return [shim_remove_pdf_obj_refs(field[0]) for field in the_file[0].get_pdf_fields()]
  else:
    if the_file.mimetype == 'application/pdf':
      return [shim_remove_pdf_obj_refs(field[0]) for field in the_file.get_pdf_fields()]

  docx_data = docx2python( the_file.path() )  # Will error with invalid value
  text = docx_data.text
  return get_docx_variables( text )

def shim_remove_pdf_obj_refs(value):
  """
  Recursively process PDF fields with unresolved PDFObjRefs so that they can be pickled and also
  so that we can determine max char length.
  
  TODO: unneeded if https://github.com/jhpyle/docassemble/pull/413 is merged.
  """
  if isinstance(value, PDFObjRef):
    temp_val = resolve1(value)
    if isinstance(temp_val, list): # I think only options are lists, PDFObjRefs, or base types
      temp_list = []
      for val in temp_val:
        if isinstance(val, PDFObjRef):
          temp_list.append(shim_remove_pdf_obj_refs(val))
        else:
          temp_list.append(val)
      return temp_list
    return temp_val
  return value
      

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
          
    if '.mailing_address' in possible_var:  # a mailing address
      if '.mailing_address.county' in possible_var:  # a county is special
        fields.add( possible_var )
      else:  # all other mailing addresses (replaces .zip and such)
        fields.add( re.sub(r'\.mailing_address.*', '.mailing_address.address', possible_var ))
      continue

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

    if '.name' in possible_var:  # a name
      if '.name.text' in possible_var:  # Names for non-Individuals
        fields.add( possible_var )
      else:  # Names for Individuals
        fields.add( re.sub(r'\.name.*', '.name.first', possible_var ))
      continue

    # Replace any methods at the end of the variable with the attributes they use
    possible_var = substitute_suffix(possible_var, 
                                     generator_constants.DISPLAY_SUFFIX_TO_SETTABLE_SUFFIX)
    methods_removed = re.sub( r'(.*)\..*\(.*\)', '\\1', possible_var)
    fields.add( methods_removed )

  return fields


########################################################
# Map names code

def map_raw_to_final_display(label:str, document_type:str="pdf",
              reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
              custom_people_plurals_map=custom_values.people_plurals_map,
              reserved_prefixes=generator_constants.RESERVED_PREFIXES,
              undefined_person_prefixes=generator_constants.UNDEFINED_PERSON_PREFIXES,
              reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP,
              reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP) -> str:
  """For a given set of specific cases, transform a
  PDF field name into a standardized object name
  that will be the value for the attachment field."""
  if document_type.lower() == "docx" or '.' in label:
    return label # don't transform DOCX variables

  # Turn spaces into `_`, strip non identifier characters
  label = varname(label)

  # Remove multiple appearance indicator, e.g. '__4' of 'users__4'
  label = remove_multiple_appearance_indicator(label)

  if (label in reserved_whole_words
   or label in reserved_pluralizers_map.values() 
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
  if (adjusted_prefix in reserved_pluralizers_map.values()
      or adjusted_prefix in custom_people_plurals_map.values()):
    digit_str = label_groups[2]
    if digit_str == '':
      index = '[0]'
    else:
      try:
        digit = int(digit_str)
      except ValueError as ex:
        raise ParsingException('{} is not a digit'.format(digit_str),
            'Full issue: {}. This is likely a developer error! ' + \
            'Please [let us know](https://github.com/SuffolkLITLab/docassemble.ALWeaver/issues/new)!'.format(ex))

      if digit == 0:
        main_issue = 'Cannot get the 0th item in a list'
        err_str = 'The "{}" label refers to the 0th item in a list, when it is likely meant the 1st item. You should replace that label with "{}".'.format(
          label, adjusted_prefix + '1' + label_groups[3])
        url = "https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/label_variables#more-than-one"
        raise ParsingException(main_issue, err_str, url)
      else:
        index = '[' + str(digit - 1) + ']'
  else:
    digit_str = ''
    index = ''
  
  # it's just a standalone, like "defendant", or it's a numbered singular
  # prefix, e.g. user3
  if label == prefix or label == prefix + digit_str:
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
                           reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP,
                           allow_singular_suffixes=generator_constants.ALLOW_SINGULAR_SUFFIXES):
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
          or len(docx_suffixes_matches) > 0) and (prefix in allow_singular_suffixes or label_parts[0][0].endswith(']')):
          # We do NOT want users.address.address to match, only users[0].address.address
          # but we do allow trial_court.address.address. Make sure we don't overmatch
        return True

    # For all other cases
    return False


############################
#  Identify reserved PDF labels
############################
def is_reserved_label(label, reserved_whole_words = generator_constants.RESERVED_WHOLE_WORDS, reserved_prefixes = generator_constants.RESERVED_PREFIXES, reserved_pluralizers_map = generator_constants.RESERVED_PLURALIZERS_MAP, reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
  '''Given a PDF label, returns whether the label fully
    matches a reserved prefix or a reserved prefix with a
    reserved suffix'''

  # Get rid of all multi-appearance indicators, e.g. '__4' of 'user_name__4'
  # Doesn't matter if it's a first appearance or more
  label = remove_multiple_appearance_indicator(label)

  if label in reserved_whole_words:
    return True
  # For the sake of time, this is the fastest way to get around something being plural
  if label in reserved_pluralizers_map.values():
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
      fields_to_add.add(field)
      delete_list.append(field) # Cannot mutate in place
    else:
      # check for possible DOCX match of prefix + suffix, w/ [index] removed
      matching_docx_test = r"^(" + "|".join(custom_people) + ")\[\d+\](" + ("|".join([suffix.replace(".","\.") for suffix in people_suffixes])) + ")$"
      log(matching_docx_test)
      if re.match(matching_docx_test, field.variable):
        delete_list.append(field)
        fields_to_add.add(field)

  for field in delete_list:
    fields.remove(field)

  for field in fields_to_add:
    built_in_fields.append(field)


def get_person_variables(fieldslist,
                         undefined_person_prefixes = generator_constants.UNDEFINED_PERSON_PREFIXES,
                         people_suffixes = generator_constants.PEOPLE_SUFFIXES,
                         people_suffixes_map = generator_constants.PEOPLE_SUFFIXES_MAP,
                         reserved_person_pluralizers_map = generator_constants.RESERVED_PERSON_PLURALIZERS_MAP,
                         reserved_pluralizers_map = generator_constants.RESERVED_PLURALIZERS_MAP,
                         custom_only=False):
  """
  Identify the field names that appear to represent people in the list of
  string fields pulled from docx/PDF. Exclude people we know
  are singular Persons (such as trial_court).
  """
  people_vars = reserved_person_pluralizers_map.values()
  people = set()
  for field in fieldslist:
    # fields are currently tuples for PDF and strings for docx
    if isinstance(field, tuple):
      file_type = "pdf"
      # map_raw_to_final_display will only transform names that are built-in to the constants
      field_to_check = map_raw_to_final_display(field[0])
    else:
      file_type = "docx"
      field_to_check = field
    # Exact match
    if (field_to_check) in people_vars:
      people.add(field_to_check)
    elif (field_to_check) in undefined_person_prefixes:
      pass  # Do not ask how many there will be about a singluar person
    elif file_type == "docx" and ('[' in field_to_check or '.' in field_to_check):
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
    elif file_type == "pdf":
      # If it's a PDF name that wasn't transformed by map_raw_to_final_display, do one last check
      # In this branch and all subbranches strip trailing numbers
      # regex to check for matching suffixes, and catch things like mailing_address_address
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
    return people - set(reserved_pluralizers_map.values())
  else:
    return people - (set(reserved_pluralizers_map.values()) - set(people_vars))

def set_custom_people_map( people_var_names ):
  """Sets the map of custom people created by the developer."""
  for var_name in people_var_names:
    custom_values.people_plurals_map[ var_name ] = var_name
  return custom_values.people_plurals_map

def using_string(params:dict, elements_as_variable_list:bool=False)->str:
  """
  Create a text representation of a .using method of a DAObject class.
  Provide a dictionary of parameters as an argument.
  Returns a string like: ".using(param='value', param2=True, param3=3)"
  given a dictionary of {"param":"value","param2":True, "param3":3}.

  Parameters will be converted using `repr`.
  Special case: the parameter "elements" given a list of strings will
  be rendered as a list of variables instead if elements_as_variable_list=True.

  TODO: this is relatively rigid, but is simplest for current needs. Could easily
  adjust the template or not use this function.
  """
  if not params or len(params) < 1:
    return ""
  retval = ".using("
  params_string_builder = []
  for param in params:
    if elements_as_variable_list and param == "elements": 
      params_string_builder.append("elements=["+",".join([str(p) for p in params[param]])+"]" )
    else:
      params_string_builder.append(str(param) + "=" + repr(params[param]))
  retval += ",".join(params_string_builder)
  return retval + ")"

def pdf_field_type_str(field):
  """Gets a human readable string from a PDF field code, like '/Btn'"""
  if not isinstance(field, tuple) or len(field) < 4 or not isinstance(field[4], str):
    return ''
  else:
    if field[4] == '/Sig':
      return 'Signature'
    elif field[4] == '/Btn':
      return 'Checkbox'
    elif field[4] == '/Tx':
      return 'Text'
    else:
      return ':skull-crossbones:'

def bad_name_reason(field:Union[str, Tuple]):
  """Returns if a PDF or DOCX field name is valid for AssemblyLine or not"""
  if isinstance(field, str):
    # We can't map DOCX fields to valid variable names, but we can tell if they are valid expressions
    # TODO(brycew): this needs more work, we already filter out bad names in get_docx_variables()
    try:
      ast.parse(field)
    except SyntaxError as ex:
      return "{} isn't a valid python expression: {}".format(field, ex)
    return None
  else:
    log(field[0], 'console')
    python_var = map_raw_to_final_display(remove_multiple_appearance_indicator(varname(field[0])))
    if len(python_var) == 0:
      return '{}, the {}, should be in [snake case](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/docs/naming#pdf-variables--snake_case) and use alphabetical characters'.format(field[0], pdf_field_type_str(field))
    return None


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

  dependencies = ",".join(['\'' + dep + '\'' for dep in info['dependencies']])

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
