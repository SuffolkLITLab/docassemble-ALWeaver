from bs4 import BeautifulSoup
import copy
import json

"""
  Data flow:
  1. Initial screen load: PY make_it_draggable
    (a). outputs a draggable_table for screen display
    (b). outputs the original table order as a list to be used later          
  2. When a user adjusts the table: JS saves the adjusted table order as a list to a hidden field
  3. When the Continue button is clicked: 
    (a). PY update_table_order_var - uses 1.(b) and 2. to update an existing table order yaml var 
    (b). PY make_json - saves adjusted table data as a json string to another hidden field    
  4. When the Back button is clicked: JS updates the draggable_table with data saved by 3.(b)
"""


def make_it_draggable(tbl_data) -> list:
    """
    This function makes a markdown template table draggable:
    1. Add required class name and attributes required to activate the drag-and-drop js functions.
    2. Save the origina screen order as a list, to be used in def adjust_order.
    """
    # Convert the table into html
    original = tbl_data.content_as_html()

    # Add a class name to the table
    soup = BeautifulSoup(original, "html.parser")
    tag = soup.table["class"]
    tag.append("draggable-table")

    # Add attributes to <tr> elements but skip the title row
    for row in soup.find_all("tr")[1:]:
        row["class"] = "drag"
        row["draggable"] = "true"
        row["ondragstart"] = "start()"
        row["ondragover"] = "dragover()"

    # Save the screen name column into a list
    original_order = []
    for row in soup.find_all("tr")[1:]:
        cell = row.find_all("td")[1].get_text()
        original_order.append(cell)

    return [original_order, str(soup)]


def update_table_order_var(old_table_order, new_table_order, old_object):
    """
    1. old_table_order came from make_it_draggable, new_table_order came from JS, both are simple lists.
    2. old_object is a DAList object used to build code blocks for the output interview.
    This function copies data from old_object to a new DAList using the three input items, and the end result is the reordered(updated) version of old_object.
    """
    # Convert new_table_order (updated via js) from string to list
    adjusted_order = []
    adjusted_order = new_table_order.split(",")

    # Copy DAList structure from old_object to new_object
    new_object = copy.deepcopy(old_object)
    new_object.clear()

    for scr in adjusted_order:
        # Find the row index of scr in the original table
        old_position = old_table_order.index(scr)

        # Use that index to copy the row from old_object into new_object
        new_object.append(old_object[old_position])

    # Return a reordered DAList object
    return new_object


def make_json(order, old_html):
    """
    This function saves the adjusted table data as a json string, so that it can be passed to a hidden field on the table screen.
    1. Use the reordered index (order) saved by JS to copy matching rows from the original table old_soup to a list
    2. Convert the list to json
    """

    old_soup = BeautifulSoup(old_html, "html.parser")
    # 1. Convert adjusted table order from string to list
    adjusted_order = []
    adjusted_order = order.split(",")

    # 2. Prepare for json string
    collections = list()
    headings = list()
    headings = old_soup.find_all("th")

    # 3. Loop thru the adjusted order and copy data from old_soup to collections
    for j, row_name in enumerate(adjusted_order):

        # Handle one row at a time.
        old_tbl_rows = old_soup.find_all("tr")[1:]  # skip heading row
        for old_row in old_tbl_rows:
            old_cells = old_row.find_all("td")

            if row_name in old_cells[1].get_text():  # found a matching row (field name)
                # Create a dict record using heading as its keys.
                record = copy_one_row(headings, j + 1, old_row)
                # 3.3 Save the record dict to a list
                collections.append(record)

    # 4. Return the results as a json string
    return json.dumps(collections)


def copy_one_row(heading, index, row):
    record = dict()
    tds = row.find_all("td")

    # 1. Save adjusted table order as the 1st pair in the json record
    record.update({str(heading[0].text): str(index)})

    # 2. Copy the rest of the columns
    for k in range(1, len(heading)):
        # Save links differently. Not all rows have a link.
        a_tag = tds[k].find("a")
        if a_tag is not None:
            record[str(heading[k].text).replace(" ", "_")] = str(a_tag)
        else:
            # Multi-words heading on the screen allows space in between, but not so in json string keys
            # which are used in JS to update the draggable table, so we'll convert space to "_" here.
            #  e.g. 'Number of fields' will be converted to Number_of_fields.
            record.update({str(heading[k].text).replace(" ", "_"): tds[k].text})

    return record
