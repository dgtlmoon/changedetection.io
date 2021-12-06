// table tools

// sorting
function sortTable(n) {
  var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
  table = document.getElementById("watch-table");
  switching = true;
  //Set the sorting direction to ascending:
  dir = "asc"; 
  /*Make a loop that will continue until
  no switching has been done:*/
  while (switching) {
    //start by saying: no switching is done:
    switching = false;
    rows = table.rows;
    /*Loop through all table rows (except the
    first, which contains table headers):*/
    for (i = 1; i < (rows.length - 1); i++) {
      //start by saying there should be no switching:
      shouldSwitch = false;
      /*Get the two elements you want to compare,
      one from current row and one from the next:*/
      x = rows[i].getElementsByTagName("TD")[n];
      y = rows[i + 1].getElementsByTagName("TD")[n];
      x = x.innerHTML.toLowerCase();
      y = y.innerHTML.toLowerCase();
	  /* handle # columns */
	  if (!isNaN(x)) { 
		x = parseFloat(x);
		y = parseFloat(y);
	  }
	  /*check if the two rows should switch place,
      based on the direction, asc or desc:*/
      if (dir == "asc") {
		if (x > y) {
          //if so, mark as a switch and break the loop:
          shouldSwitch= true;
          break;
        }
      } else if (dir == "desc") {
        if (x < y) {
          //if so, mark as a switch and break the loop:
          shouldSwitch = true;
          break;
        }
      }
    }
    if (shouldSwitch) {
      /*If a switch has been marked, make the switch
      and mark that a switch has been done:*/
      rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
      switching = true;
      //Each time a switch is done, increase this count by 1:
      switchcount ++;      
    } else {
      /*If no switching has been done AND the direction is "asc",
      set the direction to "desc" and run the while loop again.*/
      if (switchcount == 0 && dir == "asc") {
        dir = "desc";
        switching = true;
      }
    }
  }

  // hide all asc/desc sort arrows
  sortimgs = document.querySelectorAll('[id^="sort-"]');
  for (var i = 0; i < sortimgs.length; i++) {
	sortimgs[i].style.display = "none";
  }

  // show current asc/desc sort arrow
  if (dir == "asc") {
    document.getElementById("sort-" + n + "a").style.display = "";
  }
  else {
	document.getElementById("sort-" + n + "d").style.display = "";
  }

  // show all sortable indicators
  sortableimgs = document.querySelectorAll('[id^="sortable-"]');
  for (var i = 0; i < sortableimgs.length; i++) {
    sortableimgs[i].style.display = "";
  }
  
  // hide sortable indicator from current column
  document.getElementById("sortable-" + n).style.display = "none";

}

// check/uncheck all checkboxes
function checkAll(e) {
	var checkboxes = document.getElementsByName('check');
	
	if (e.checked) {
		for (var i = 0; i < checkboxes.length; i++) {  
			checkboxes[i].checked = true;
		}
	} else {
		for (var i = 0; i < checkboxes.length; i++) {
			checkboxes[i].checked = false;
		}
	}
}

// check/uncheck the checkall checkbox if the all checkboxes are checked or unchecked
function checkChange(){
	
	var totalCheckbox = document.querySelectorAll('input[name="check"]').length;
	var totalChecked = document.querySelectorAll('input[name="check"]:checked').length;
	
	// Total checkboxes equals to total checked checkboxes
	if(totalCheckbox == totalChecked) {
		document.getElementsByName("showhide")[0].checked=true;
	} else {
		document.getElementsByName("showhide")[0].checked=false;
	}
}

// search watches in Title column
function tblSearch(evt, input) {

  var code = evt.charCode || evt.keyCode;
  if (code == 27) {
    document.getElementById("txtInput").value = '';
  }
  var input, filter, table, tr, td, i, txtValue;
  input = document.getElementById("txtInput");
  filter = input.value.toUpperCase();
  table = document.getElementById("watch-table");
  tr = table.getElementsByTagName("tr");
  for (i = 0; i < tr.length; i++) {
    td = tr[i].getElementsByTagName("td")[4]; // [4] is Title column
    if (td) {
      txtValue = td.textContent || td.innerText;
      if (txtValue.toUpperCase().indexOf(filter) > -1) {
        tr[i].style.display = "";
      } else {
        tr[i].style.display = "none";
      }
    }       
  }
}

// get checked or all uuids
function getChecked(items) {
	
	if ( items === undefined ) {
		var checkedArr = document.querySelectorAll('input[name="check"]:checked');
	}
	else {
		var checkedArr = document.querySelectorAll('input[name="check"]');
	}
	
	if ( checkedArr.length > 0 ) {
	
		let output = [];
		
		for (var i = 0; i < checkedArr.length; i++  ) {
			output.push( checkedArr[i].parentNode.parentNode.getAttribute("id") );
		}

		var uuids = ""
		for (var i = 0; i < checkedArr.length; i++  ) {
			if (i < checkedArr.length - 1 ) {
				uuids += output[i] + ",";
			} else {
				uuids += output[i];
			}
		}

	} else {
		uuids = '';
	}

	return uuids;
}

// process selected watches 
function processChecked(func, tag) {

	if ( func == 'mark_all_unviewed' ) {
		uuids = getChecked('all');
	}
	else {
		uuids = getChecked();
	}
	
	var frm = document.getElementById("process-selected");

	var func_field = document.getElementById("func");
	
	var tag_field = document.getElementById("tag");

	var uuid_field = document.getElementById("uuids");
	
	func_field.value = func;
	
	tag_field.value = tag;

	uuid_field.value = uuids;

	if ( uuids != '' ) {
		
		if ( func == 'mark_selected_unviewed' ) {
			// fall through and submit
		}
		else if ( func == 'mark_selected_viewed' ) {
			// fall through and submit
		}
		else if ( func == 'mark_all_unviewed' ) {
			// fall through and submit
		}
		else if ( func == 'recheck_selected' ) {
			// fall through and submit
		}
		else if ( func == 'delete_selected' ) {
	
			// confirm deletion
			result = confirm('Deletions cannot be undone.\n\nAre you sure you want to continue?');
			
			if ( result == false) {
				return;
			}
		}
		else {
			// invalid input
			return;
		}

	}
	
	// api will either process or flash 'no uuids selected'
	frm.submit();

}

function clearSearch() {
	document.getElementById("txtInput").value = '';
	tblSearch(27, this);
}