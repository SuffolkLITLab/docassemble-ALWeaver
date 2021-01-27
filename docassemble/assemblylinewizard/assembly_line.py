from docassemble.webapp.playground import *
from docassemble.base.util import DAList


class DAQuestionList(DAList):
  def init(self, **kwargs):
    super().init(**kwargs)
    self.object_type = DAQuestion
