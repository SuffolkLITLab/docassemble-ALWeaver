from typing import Dict, List, Tuple

from bs4 import BeautifulSoup
from bs4.element import Tag
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


def make_it_draggable(tbl_data) -> Tuple[List[str], str]:
    """
    This function makes a markdown template table draggable:
    1. Add required class name and attributes required to activate the drag-and-drop js functions.
    2. Save the origina screen order as a list, to be used in def adjust_order.
    """
    # Convert the table into html
    original = tbl_data.content_as_html()

    # Add a class name to the table
    soup = BeautifulSoup(original, "html.parser")
    table_tag = soup.find("table")
    if not isinstance(table_tag, Tag):
        empty_order: List[str] = []
        return (empty_order, original)

    existing_classes_attr = table_tag.get("class")
    classes_list: List[str]
    if isinstance(existing_classes_attr, list):
        classes_list = list(existing_classes_attr)
    elif isinstance(existing_classes_attr, str):
        classes_list = existing_classes_attr.split()
    else:
        classes_list = []

    if "draggable-table" not in classes_list:
        classes_list.append("draggable-table")

    table_tag["class"] = " ".join(classes_list)

    rows: List[Tag] = [tr for tr in soup.find_all("tr") if isinstance(tr, Tag)]

    # Add attributes to <tr> elements but skip the title row
    for row in rows[1:]:
        row["class"] = "drag"
        row["draggable"] = "true"
        row["ondragstart"] = "start()"
        row["ondragover"] = "dragover()"

    # Save the screen name column into a list
    original_order: List[str] = []
    for row in rows[1:]:
        cells = [td for td in row.find_all("td") if isinstance(td, Tag)]
        if len(cells) > 1:
            original_order.append(cells[1].get_text())

    return (original_order, str(soup))


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


def make_json(order: str, old_html: str) -> str:
    """
    This function saves the adjusted table data as a json string, so that it can be passed to a hidden field on the table screen.
    1. Use the reordered index (order) saved by JS to copy matching rows from the original table old_soup to a list
    2. Convert the list to json
    """

    old_soup = BeautifulSoup(old_html, "html.parser")
    # 1. Convert adjusted table order from string to list
    adjusted_order: List[str] = [item for item in order.split(",") if item]

    # 2. Prepare for json string
    collections: List[Dict[str, str]] = []
    headings: List[Tag] = [tag for tag in old_soup.find_all("th") if isinstance(tag, Tag)]
    table_rows: List[Tag] = [tr for tr in old_soup.find_all("tr") if isinstance(tr, Tag)]
    data_rows = table_rows[1:]

    # 3. Loop thru the adjusted order and copy data from old_soup to collections
    for j, row_name in enumerate(adjusted_order):
        if not row_name:
            continue
        for old_row in data_rows:  # skip heading row already accounted for
            old_cells = [td for td in old_row.find_all("td") if isinstance(td, Tag)]

            if len(old_cells) > 1 and row_name in old_cells[1].get_text():
                # Create a dict record using heading as its keys.
                record = copy_one_row(headings, j + 1, old_row)
                # 3.3 Save the record dict to a list
                collections.append(record)

    # 4. Return the results as a json string
    return json.dumps(collections)


def copy_one_row(heading: List[Tag], index: int, row: Tag) -> Dict[str, str]:
    record: Dict[str, str] = dict()
    tds = [td for td in row.find_all("td") if isinstance(td, Tag)]

    # 1. Save adjusted table order as the 1st pair in the json record
    if heading:
        record.update({str(heading[0].text): str(index)})

    # 2. Copy the rest of the columns
    for k in range(1, min(len(heading), len(tds))):
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
