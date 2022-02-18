$(document).on('daPageLoad', function(){            
    // Grab the field for storing adjusted table order
    var orderList = $('input[type="draggable_tbl_order_list"]');
    $(orderList).hide(); 
    
    // Grab field scr_table_data (with default value json_string)    
    var json_data = $('input[type="draggable_tbl_json_string"]');    
    $(json_data).hide();  
    
    // If user adjusted the table order, update draggable_table with data from json_data     
    var draggable_table = $('.draggable-table');      
    // Must use $(orderList), not orderList
    if ($(orderList).val() != undefined) {
      if ($(orderList).val() != '') {
        var json_records = JSON.parse($(json_data).val());  
        update_table(draggable_table, json_records);
      };
    };  
});

// Drag and drop functions - only screens with a draggable table will call them
var row;
function start(){
  row = event.target;
}
function dragover(){
  var e = event;
  e.preventDefault();

  let children= Array.from(e.target.parentNode.parentNode.children);
  if(children.indexOf(e.target.parentNode)>children.indexOf(row))
    e.target.parentNode.after(row);
  else
    e.target.parentNode.before(row);

  // Save the adjusted order data to the backend for later use
  SaveReorder(row);    
}
function SaveReorder(r){
  table = r.parentNode;  
  var my_list = [];
  
  for (var i = 0, my_row; my_row = table.rows[i]; i++) {    
    // Set the first column to the rowindex on the screen 
    my_row.cells[0].innerHTML = my_row.rowIndex;
    
    // Append the screen name to my_list
    my_list.push(my_row.cells[1].innerHTML); 
  }
  
  // Save the order to a hidden field on the screen
  $('input[type="draggable_tbl_order_list"]').val(my_list); 
}

// Update draggable_table on the screen with data from the hidden field
function update_table(tbl, json_records){     
  var rows = tbl.find('tr');  
  
  // Loop thru the table itself, but skip the heading row.
  for (var i = 1, row; row = rows[i]; i++) {      
    // Loop thru json data records (rows)
    for (let k = 0; k < json_records.length; k++){
      // Find the matching row by the table index and json record index      
      if (i-1 == k){        
        // Update the matching row (using the kth record in json_records)       
        var one_record = json_records[k];
        UpdateOneRow(one_record, row);        
      };
    };  // end of json data loop   
  }; // end of table row loop 
};

function UpdateOneRow(one_record, row){
  // Loop thru key/value pairs in one json record 
  var index = 0;
  for (var key in one_record){						
    var value = one_record[key];        
    // Update the matching row in draggable_table by looping thru its columns        
    for (var m = 0; m < row.cells.length; m++){
      // Find matching cell by json record's index and table column's index      
      if (m == index){         
      // update cell content			                              
        row.cells[m].innerHTML = value;           
      }; // end of matching cell            
    }; //  end of matching row    
    index += 1;  
  };
}