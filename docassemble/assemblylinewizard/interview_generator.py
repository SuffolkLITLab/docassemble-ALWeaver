import os
import re
import keyword
import copy
import sys
import yaml
import tempfile
from docx2python import docx2python
from docassemble.webapp.files import SavedFile, get_ext_and_mimetype, make_package_zip
from docassemble.base.pandoc import word_to_markdown, convertible_mimetypes, convertible_extensions
from docassemble.base.error import DAError
from docassemble.base.util import log, space_to_underscore, bold, DAObject, DADict, DAList, DAFile, DAFileList
import docassemble.base.functions
import docassemble.base.parse
import docassemble.base.pdftk
import shutil
import datetime
import zipfile
import types
import json
from .generator_constants import generator_constants

TypeType = type(type(None))

__all__ = ['Playground', 'PlaygroundSection', 'indent_by', 'varname', 'DAField', 'DAFieldList', 'DAQuestion', 'DAInterview', 'DAAttachmentList', 'DAAttachment', 'to_yaml_file', 'base_name', 'to_package_name', 'oneline', 'DAQuestionList', 'map_names', 'trigger_gather_string', 'is_reserved_label', 'attachment_download_html', 'get_fields','is_reserved_docx_label','get_character_limit', 'create_package_zip', 'get_person_variables', 'get_court_choices']

always_defined = set(["False", "None", "True", "dict", "i", "list", "menu_items", "multi_user", "role", "role_event", "role_needed", "speak_text", "track_location", "url_args", "x", "nav", "PY2", "string_types"])
replace_square_brackets = re.compile(r'\\\[ *([^\\]+)\\\]')
start_spaces = re.compile(r'^ +')
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
  """A field represents a Docassemble field/variable. I.e., a single piece of input we are gathering from the user."""
  def init(self, **kwargs):
    return super().init(**kwargs)

  def fill_in_docx_attributes(self, new_field_name,
                              reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP):
    """The DAField class expects a few attributes to be filled in.
    In a future version of this, maybe we can use context to identify
    true/false variables. For now, we can only use the name.
    We have a lot less info than for PDF fields.
    """
    self.variable = new_field_name
    self.docassemble_variable = new_field_name  # no transformation changes
    self.trigger_gather = trigger_gather_string(self.docassemble_variable)
    self.has_label = True

    # this will let us edit the name field if document just refers to
    # the whole object
    if new_field_name in reserved_pluralizers_map.values():
      self.edit_attribute = new_field_name + '[0].name.first'
    if new_field_name in [label + '[0]' for label in reserved_pluralizers_map.values()]:
      self.edit_attribute = new_field_name + '.name.first'

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
    self.variable = varname(pdf_field_tuple[0])
    self.docassemble_variable = map_names(pdf_field_tuple[0])  # TODO: wrap in varname
    self.trigger_gather = trigger_gather_string(self.docassemble_variable)

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

  def get_single_field_screen(self, document_type):
    field_name_to_use = map_names(self.variable, document_type=document_type)
    if self.field_type == 'yesno':
      return "yesno: {}\n".format(field_name_to_use), True
    elif self.field_type == 'yesnomaybe':
      return "yesnomaybe: {}\n".format(field_name_to_use), True
    else:
      return "", False

  def _maxlength_str(self):
    if hasattr(self, 'maxlength') and self.maxlength:
      return "    maxlength: {}".format(self.maxlength)
    else:
      return ""

  def field_entry_yaml(self, document_type):
    field_name_to_use = map_names(self.variable, document_type=document_type)
    content = ""
    if self.has_label:
      content += "  - {}: {}\n".format(repr_str(self.label), field_name_to_use)
    else:
      content += "  - no label: {}\n".format(field_name_to_use)

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

  def review_yaml(self, document_type, field_names):
    field_name_to_use = unmap(map_names(self.variable, document_type=document_type))
    if field_name_to_use in field_names:
      return ""

    content = ""
    if hasattr(self, 'edit_attribute'):
      content += '  - Edit: ' + self.edit_attribute + "\n"
    else:
      content += '  - Edit: ' + field_name_to_use + "\n"
    content += '    button: |\n'
    edit_display_name = self.label if hasattr(self, 'label') else field_name_to_use
    content += indent_by(bold(edit_display_name) + ": ", 6)
    if hasattr(self, 'field_type'):
      if self.field_type in ['yesno', 'yesnomaybe']:
        content += indent_by('${ word(yesno(' + field_name_to_use + ')) }', 6)
      elif self.field_type in ['integer', 'number','range']:
        content += indent_by('${ ' + field_name_to_use + ' }', 6)
      elif self.field_type == 'area':
        content += indent_by('> ${ single_paragraph(' + field_name_to_use + ') }', 6)
      elif self.field_type == 'file':
        content += "      \n"
        content += indent_by('${ ' + field_name_to_use + ' }', 6)
      elif self.field_type == 'currency':
        content += indent_by('${ currency(' + field_name_to_use + ') }', 6)
      elif self.field_type == 'date':
        content += indent_by('${ ' + field_name_to_use + '.format() }', 6)
      # elif field.field_type == 'email':
      else:
        content += indent_by('${ ' + field_name_to_use + ' }', 6)
    else:
      content += indent_by('${ ' + field_name_to_use + ' }', 6)
    field_names.add(field_name_to_use)
    return content

  def attachment_yaml(self):
    # Lets use the list-style, not dictionary style fields statement
    # To avoid duplicate key error
    field_varname = varname(self.variable)
    content = '      - "{}": '.format(self.variable)
    if hasattr(self, 'field_type') and self.field_type == 'date':
        content += '${ ' + field_varname.format() + ' }\n'
    elif hasattr(self, 'field_type') and self.field_type == 'currency':
        content += '${ currency(' + field_varname + ') }\n'
    elif hasattr(self, 'field_type') and self.field_type == 'number':
        content += r'${ "{:,.2f}".format(' + field_varname + ') }\n' 
    elif self.field_type_guess == 'signature': 
      comment = "      # It's a signature: test which file version this is; leave empty unless it's the final version)\n"
      content = comment + content + '${ ' + map_names(field_varname) + " if i == 'final' else '' }\n"
    else:
      content += '${ ' + map_names(field_varname) + ' }\n'
    log('attachment_yaml for {}: {}'.format(self.variable, content), 'console')
    return content

  def user_ask_about_field(self, index):
    field_questions = []
    if self.variable != self.docassemble_variable:
      field_questions.append({
        'note': bold('{} (will be renamed to {})'.format(self.variable, self.docassemble_variable))
      })
    else:
      field_questions.append({
        'note': bold(self.variable)
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


class DAFieldList(DAList):
    """A DAFieldList contains multiple DAFields."""
    def init(self, **kwargs):
        self.object_type = DAField
        self.auto_gather = False
        # self.gathered = True
        return super().init(**kwargs)
    def __str__(self):
        """I don't think this method has a real function in our code base. Perhaps debugging."""
        return docassemble.base.functions.comma_and_list(map(lambda x: '`' + x.variable + '`', self.elements))


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
            if hasattr(self,'has_mandatory_field') and not self.has_mandatory_field:
              content += "continue button field: " + varname(self.question_text) + "\n"
            elif hasattr(self, 'continue_button_field'):
              content += "continue button field: " + varname(self.continue_button_field) + "\n"
            content += "question: |\n" + indent_by(self.question_text, 2)
            if self.subquestion_text != "":
                content += "subquestion: |\n" + indent_by(self.subquestion_text, 2)
            if len(self.field_list) == 1:
                new_content, done_with_content = self.field_list[0].get_single_field_screen(document_type)
                content += new_content
            if self.field_list[0].field_type == 'end_attachment':
                if hasattr(self, 'interview_label'):  # this tells us its the ending screen
                  # content += "buttons:\n  - Exit: exit\n  - Restart: restart\n" # we don't want people to erase their session
                  content += "need: " + self.interview_label + "\n"
                  # TODO: insert the email code
                  #content += "attachment code: " + self.attachment_variable_name + "['final']\n"
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
                    content += "attachment:\n"
                    content += "    variable name: " + self.attachment_variable_name + "[i]\n"
                    content += "    name: " + oneline(attachment.name) + "\n"
                    content += "    filename: " + varname(attachment.name) + "\n"
                    if attachment.type == 'md':
                        content += "    content: " + oneline(attachment.content) + "\n"
                    elif attachment.type == 'pdf':
                        content += "    skip undefined: True" + "\n"
                        content += "    pdf template file: " + oneline(attachment.pdf_filename) + "\n"
                        self.templates_used.add(attachment.pdf_filename)
                        content += "    fields: " + "\n"
                        for field in attachment.fields:
                          content += field.attachment_yaml()
                    elif attachment.type == 'docx':
                        content += "    docx template file: " + oneline(attachment.docx_filename) + "\n"
                        self.templates_used.add(attachment.docx_filename)
                done_with_content = True
            if not done_with_content:
                content += "fields:\n"
                for field in self.field_list:
                    content += field.field_entry_yaml(document_type)

        elif self.type == 'signature':
            content += "signature: " + varname(self.field_list[0].variable) + "\n"
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
            content += "\n"
                                   
        elif self.type == 'interview order':
            # TODO: refactor this. Too much of it is assembly-line specific code
            # move into the interview YAML or a separate module/subclass
            content += "id: interview_order_" + self.interview_label + "\n"
            content += "code: |\n"
            content += "  # This is a placeholder to control logic flow in this interview" + "\n"
            signatures = set()
            added_field_names = set()
            for field in self.logic_list:
              if field.endswith('.signature'):  # save the signatures for the end
                signatures.add(field)
              elif not field in added_field_names:
                # We built this logic list by collecting the first field on each screen
                content += "  " + field + "\n"
              added_field_names.add(field)
            content += "  " + self.interview_label + '_preview_question # Pre-canned preview screen\n'
            content += "  basic_questions_signature_flow\n"
            for signature_field in signatures:
              content += "  " + signature_field + "\n"
            content += "  " + self.interview_label + " = True" + "\n"
        elif self.type == 'text_template':
            content += "template: " + varname(self.field_list[0].variable) + "\n"
            if hasattr(self, 'template_subject') and self.template_subject:
                content += "subject: " + oneline(self.template_subject) + "\n"
            if self.template_type == 'file':
                content += "content file: " + oneline(self.template_file) + "\n"
            else:
                content += "content: |\n" + indent_by(self.template_body, 2)
        elif self.type == 'template':
            content += "template: " + varname(self.field_list[0].variable) + "\n"
            content += "content file: " + oneline(self.template_file) + "\n"
            self.templates_used.add(self.template_file)
        elif self.type == 'sections':
            content += "features:\n  navigation: True\n"
            content += '---\n'
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
            content += "    'title': '" + escape_quote(oneline(self.title)) + "',\n"
            content += "    'short title': '" + escape_quote(oneline(self.short_title)) + "',\n"
            content += "    'description': '" + escape_quote(oneline(self.description)) + "',\n"
            content += "    'original_form': '" + escape_quote(oneline(self.original_form)) + "',\n"
            content += "    'allowed courts': " + "[\n"
            for court in self.allowed_courts.true_values():
              content += "      '" + oneline(court) + "',\n"
            content += "    ],\n"
            content += "    'categories': [" + "\n"
            for category in self.categories.true_values():
              content += "      '" + oneline(category) + "',\n"
            if self.categories['Other']:
              for category in self.other_categories.split(','):
                content += "      '" + escape_quote(oneline(category.strip())) + "',\n"
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
            content += "id: " + oneline(self.question_text) + "\n"
          content += 'continue button field: ' + self.continue_button_field + "\n"
          content += "question: |\n"
          content += indent_by(self.question_text, 2)
          content += "subquestion: |\n"
          content += indent_by(self.subquestion_text, 2)
        elif self.type == "review":
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
          field_names = set()
          for field in self.field_list:
              content += field.review_yaml(document_type, field_names)
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
            extension, mimetype = get_ext_and_mimetype(the_file)
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
        extension, mimetype = get_ext_and_mimetype(filename)
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
        extension, mimetype = get_ext_and_mimetype(filename)
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
            has_error = False
        except Exception as errmess:
            has_error = True
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
    var_name = start_spaces.sub(r'', var_name)
    var_name = end_spaces.sub(r'', var_name)
    var_name = spaces.sub(r'_', var_name)
    var_name = invalid_var_characters.sub(r'', var_name)
    var_name = digit_start.sub(r'', var_name)
    return var_name

def oneline(text):
    '''Replaces all new line characters with a space'''
    text = newlines.sub(r' ', text)
    return text

def escape_quote(text):
    return text.replace("'", "\\'")

def to_yaml_file(text):
    text = varname(text)
    text = re.sub(r'\..*', r'', text)
    text = re.sub(r'[^A-Za-z0-9]+', r'_', text)
    return text + '.yml'

def base_name(filename):
    return os.path.splitext(filename)[0]

def to_package_name(text):
    text = varname(text)
    text = re.sub(r'\..*', r'', text)
    text = re.sub(r'[^A-Za-z0-9]', r'', text)
    return text

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


def get_docx_variables( text ):
  '''Given the string from a docx file with fairly simple
  code), returns a list of the jinja variables used there.
  Can be easily tested in a repl using the libs keyword and re.'''

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

    # Deal with special cases harshly
    if '.address' in possible_var:  # an address
      if '.address.county' in possible_var:  # a county is special
        fields.add( possible_var )
      else:  # all other addresses (replaces .zip and such)
        fields.add( re.sub(r'\.address.*', '.address.address', possible_var ))
      fields.add( prefix_with_key )
      continue
      
    if '.mail_address' in possible_var:  # a mailing address
      if '.mail_address.county' in possible_var:  # a county is special
        fields.add( possible_var )
      else:  # all other mailing addresses (replaces .zip and such)
        fields.add( re.sub(r'\.mail_address.*', '.mail_address.address', possible_var ))
      fields.add( prefix_with_key )
      continue

    if '.name' in possible_var:  # a name
      if '.name.text' in possible_var:  # Names for non-Individuals
        fields.add( possible_var )
      else:  # Names for Individuals
        fields.add( re.sub(r'\.name.*', '.name.first', possible_var ))
      fields.add( prefix_with_key )
      continue

    # Remove any methods from the end of the variable
    methods_removed = re.sub( r'(.*)\..*\(.*\)', '\\1', possible_var )
    fields.add( methods_removed )

  return fields


########################################################
# Map names code

def map_names(label, document_type="pdf", reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
              reserved_prefixes=generator_constants.RESERVED_PREFIXES,
              reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS,
              reserved_pluralizers_map = generator_constants.RESERVED_PLURALIZERS_MAP,
              reserved_suffixes_map=generator_constants.RESERVED_SUFFIXES_MAP):
  """For a given set of specific cases, transform a
  PDF field name into a standardized object name
  that will be the value for the attachment field."""
  if document_type.lower() == "docx":
    return label # don't transform DOCX variables

  # Remove multiple appearance indicator, e.g. '__4' of 'users__4'
  label = remove_multiple_appearance_indicator(label)

  if label in reserved_whole_words:
    return label

  if label in reserved_var_plurals:
    return label

  # Break up label into its parts
  label_groups = get_reserved_label_parts(reserved_prefixes, label)

  # If no matches to automateable labels were found,
  # just use the label as it is
  if label_groups is None or label_groups[1] == '':
    return label

  # With reserved words, we're always using an index
  # of the plural version of the prefix of the label
  prefix = label_groups[1]
  # Turn any singluars into plurals, e.g. 'user' into 'users'
  plural_prefix = reserved_pluralizers_map[prefix]
  digit = label_groups[2]
  index = indexify(digit)
  # it's just a standalone, like "defendant", or it's a numbered singular
  # prefix, e.g. user3
  if label == prefix or label == prefix + digit:
    return plural_prefix + index # Return the pluralized standalone variable

  # If it's a numbered singluar reserved prefix, e.g. user3
  if label == prefix + digit:
    # Return the plural plus the index, e.g. users[2]
    return plural_prefix + index

  suffix = label_groups[3]
  # Avoid transforming arbitrary suffixes into attributes
  if not suffix in reserved_suffixes_map:
    return label  # return it as is

  # Get the mapped suffix attribute if present, else just use the same suffix
  suffix_as_attribute = reserved_suffixes_map.get(suffix, suffix)
  return "".join([plural_prefix, index, suffix_as_attribute])


def trigger_gather_string(docassemble_var,
                          reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
                          reserved_var_plurals=generator_constants.RESERVED_VAR_PLURALS,
                          reserved_pluralizers_map=generator_constants.RESERVED_PLURALIZERS_MAP):
  """Turn the docassemble variable string into an expression
  that makes DA ask a question for it. This is mostly
  calling `gather()` for lists"""
  GATHER_CALL = '.gather()'
  if docassemble_var in reserved_whole_words:
    return docassemble_var

  if docassemble_var in reserved_var_plurals:
    return docassemble_var + GATHER_CALL

  # Everything before the first period and everything from the first period to the end
  var_with_attribute = unmap(docassemble_var)
  var_parts = re.findall(r'([^.]+)(\.[^.]*)?', var_with_attribute)

  # test for existence (empty strings result in a tuple)
  if not var_parts:
    return docassemble_var
  # The prefix, ensuring no key or index
  prefix = re.sub(r'\[.+\]', '', var_parts[0][0])
  has_plural_prefix = prefix in reserved_pluralizers_map.values()

  if has_plural_prefix:
    first_attribute = var_parts[0][1]
    if first_attribute == '' or first_attribute == '.name':
      return prefix + GATHER_CALL
    else:
      return var_parts[0][0] + first_attribute
  else:
    return docassemble_var


def is_reserved_docx_label(label, docx_only_suffixes=generator_constants.DOCX_ONLY_SUFFIXES,
                           reserved_whole_words=generator_constants.RESERVED_WHOLE_WORDS,
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
    prefix = re.sub(r'\[.+\]', '', label_parts[0][0])
    has_plural_prefix = prefix in reserved_pluralizers_map.values()

    if has_plural_prefix:
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
def remove_multiple_appearance_indicator(label):
    return re.sub(r'_{2,}\d+', '', label)

def unmap(label, unmap_suffixes=generator_constants.UNMAP_SUFFIXES):
    # map address() etc backwards
    for suffix in unmap_suffixes:
        if label.endswith(suffix):
            return label.replace(suffix, unmap_suffixes[suffix])
    return label

def get_reserved_label_parts(prefixes, label):
    return re.search(fr"{prefixes}(\d*)(.*)", label)

# Return label digit as the correct syntax for an index
def indexify(digit):
  if digit == '':
    return '[0]'
  else:
    return '[' + str(int(digit)-1) + ']'

def get_person_variables(fieldslist, people_vars=generator_constants.PEOPLE_VARS, people_suffixes = generator_constants.PEOPLE_SUFFIXES, people_suffixes_map = generator_constants.PEOPLE_SUFFIXES_MAP, reserved_person_pluralizers_map=generator_constants.RESERVED_PERSON_PLURALIZERS_MAP, custom_only=False):
  """
  Identify the field names that represent people in the list of
  string fields pulled from docx/PDF.    
  """
  people = set()
  for field in fieldslist:
    # fields are currently tuples for PDF and strings for docx
    if isinstance(field, tuple):
      field_to_check = map_names(field[0])
    else:
      field_to_check = field
    if (field_to_check) in people_vars:
      people.add(field_to_check)
    elif '[' in field_to_check or '.' in field_to_check:
      # Check for a valid Python identifier before brackets or .
      match_with_brackets_or_attribute = r"([A-Za-z_]\w*)((\[.*)|(\..*))"
      matches = re.match(match_with_brackets_or_attribute, field_to_check)
      if matches:
        # Is the name before attribute/index a predetermined person?  
        if matches.groups()[0] in people_vars:
          people.add(matches.groups()[0])
        # Maybe this is the singular version of a person's name?
        elif matches.groups()[0] in reserved_person_pluralizers_map.keys():
          people.add(reserved_person_pluralizers_map[matches.groups()[0]])          
        else:
          # Look for suffixes normally associated with people, like _name_first for PDF or .name.first for a DOCX, etc.
          if map_names(matches.groups()[1]) in people_suffixes:
            people.add(matches.groups()[0])
    else:
      # If it's a PDF name that wasn't transformed by map_names, do one last check
      # The regex below is non-greedy; _address will match before _mail_address
      match_pdf_person_suffixes = r"([A-Za-z_]\w*)(" + "|".join(people_suffixes_map.keys()) + "$)"
      matches = re.match(match_pdf_person_suffixes, field_to_check)
      if matches:
        # There may be more elegant solution. but since _mail_address_address
        # will match _address_address this is workaround below.
        # If we add more possible partial matches to suffixes, we need to add more workarounds
        if matches.groups()[0].endswith('_mail') and matches.groups()[1].startswith('_address'):
          people.add(matches.groups()[0][:-5])
        else:          
          people.add(matches.groups()[0])
  if custom_only:
    return people - set(people_vars)
  else:
    return people


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
