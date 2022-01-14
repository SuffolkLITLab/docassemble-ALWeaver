from bs4 import BeautifulSoup
import copy
import json

def make_it_draggable(tbl_data) -> list:
  """
  This function makes a markdown template table draggable:
  1. Add required class name and attributes required to activate the drag-and-drop js functions.  
  2. Save the origina screen order as a list, to be used in def adjust_order.
  """
  # Convert the table into html
  original = tbl_data.content_as_html()
  
  # Add a class name to the table  
  soup = BeautifulSoup(original, 'html.parser')
  tag = soup.table['class']
  tag.append('draggable-table')
  
  # Add attributes to <tr> elements but skip the title row
  for row in soup.find_all('tr')[1:]:
    row['class']= "drag"
    row['draggable'] = 'true'
    row['ondragstart'] = 'start()'
    row['ondragover'] = 'dragover()'  
    
  # Save the screen name column into a list
  original_order = []  
  for row in soup.find_all('tr')[1:]:    
    cell = row.find_all("td")[1].get_text()
    original_order.append(cell)  

  return [original_order, soup]	

def adjust_order(old_table_order, new_table_order, old_object, new_object):  
  """
  1. old_table_order came from make_it_draggable, new_table_order came from JS, both are simple lists.
  2. old_object is a DAList object used to build code blocks for the output interview. 
  3. new_object is a blank DAList.
  
  This function copies data from old_object to new_object using "order data/table index" from those two lists, to make new_object as the reordered version of screen_order. 
  """  
  # Convert new_table_order (updated via js) from string to list
  adjusted_order = []
  adjusted_order = new_table_order.split(',')  
    
  new_object.clear() 
  for scr in adjusted_order:
    # Find the row index of scr in the original table
    old_position = old_table_order.index(scr)

    # Use that index to copy the row from old_object into new_object
    new_object.append(old_object[old_position])

  # Return a reordered DAList object
  return new_object

def adjust_table(order, old_soup):
  """
  This function saves adjusted table data to the backend after a user adjusted the table rows:
  1. Copy the original soup object (python var to be displayed in yml) for its table structure.
  2. Use the reordered index saved by JS to copy rows from old_soup to new_soup
  3. The result is a reordered table soup object.
  """  
  # Convert new table order from string to list
  adjusted_order = []
  adjusted_order = order.split(',')    
  old_tbl_rows = old_soup.find_all('tr')[1:]    

  # Clone old_soup for its structure
  new_soup = copy.deepcopy(old_soup) 

  # Wipe out text data in new_soup
  for row in new_soup.find_all('tr')[1:]:      
    for y in range(0, 3):
      row.find_all("td")[y].string = ''            
  # Wipe out all the links 
  a_tag = new_soup.find_all('a')
  for tag in a_tag:      
    tag.decompose()   

  # Copy data from old_soup to new_soup
  for j, new_scr_name in enumerate(adjusted_order):
    # Handle one row at a time, skip header row
    for row in new_soup.find_all('tr')[j+1:j+2]: 
      # Copy adjusted scr order and name
      row.find_all("td")[0].string = str(j+1)        
      row.find_all("td")[1].string = new_scr_name        

      for r in old_tbl_rows:
        cols = r.find_all('td')            
        if new_scr_name in cols[1].get_text(): # Found the scr name 
          # Copy number of fields col        
          row.find_all("td")[2].string = cols[2].get_text()

          # Copy link - Not all rows have a link
          a_tag = r.find('a')            
          if a_tag is not None:
            row.find_all("td")[3].append(a_tag)                
  return new_soup

def make_json(soup_data): 
  """
  In order to retain the reordered table when the back button is clicked, we have to save our table data as a json string to a hidden field on the screen, which is then accessed by JS to display it.
  
  This function translates the soup object to a list of dicts, then to a json string.
  """  
  # Initialize 
  collections = list()    
  heading = list()   
  heading = soup_data.find_all('th')

  # Loop thru non-heading rows, for each row create a dict using heading as its keys.  
  for row in soup_data.find_all('tr', class_="drag"): 
    record = dict()           
    td = row.find_all('td')                 
    # Multi-words heading on the screen can allow space in between, but not so in json string keys
    # which are used in JS to update the draggable table, so we'll convert space to "_" here.
    #  e.g. 'Number of fields' will be converted to Number_of_fields.
    record.update({str(heading[0].text).replace(' ', '_'): td[0].text})
    record.update({str(heading[1].text).replace(' ', '_'): td[1].text})          
    record.update({str(heading[2].text).replace(' ', '_'): td[2].text})

    # Save links differently. Not all rows have a link      
    a_tag = row.find('a')
    if a_tag is not None: 
      record.update({str(heading[3].text): str(a_tag)}) 
    
    # Save the dict to a list
    if record:
        collections.append(record)
        
  # Make it a json string as the output 
  data = json.dumps(collections)     
  return data