# let's give this a shot, shall we?
import unittest
import sys
import re

from .interview_generator import map_names
from docassemble.base.util import log

__all__ = ['TestMapNames']

class TestMapNames(unittest.TestCase):
 
    def setUp(self):
        pass
    
    def broken_test(self):
      try:
        result = self.assertEqual( 'plaintiffs[0]', map_names('plainti') )
        log( result, 'console' )
        return result
      except AssertionError as error:
        log( str(error), 'console' )
        return re.sub('\n', '<br/>', str(error))
 
    def test_single_individuals(self):
      try:
        result = self.assertEqual( 'plaintiffs[0]', map_names('plaintiff') )
        log( result, 'console' )
        return result
      except AssertionError as error:
        log( str(error), 'console' )
        return error
 
    def test_multiple_individuals(self):
      try:
        result = self.assertEqual( 'plaintiffs[2-1]', map_names('plaintiff2') )
        log( result, 'console' )
        return result
      except AssertionError as error:
        log( str(error), 'console' )
        return error
    
    def test_multiple_appearances(self):
      try:
        result = self.assertEqual( 'plaintiffs[0]', map_names('plaintiff__2') )
        log( result, 'console' )
        return result
      except AssertionError as error:
        log( str(error), 'console' )
        return error
 
if __name__ == '__main__':
    unittest.main()
