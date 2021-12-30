// table tools

// must be a var for keyChar and keyCode use
var CONSTANT_ESCAPE_KEY = 27;
var CONSTANT_S_KEY = 83;
var CONSTANT_s_KEY = 115;

// globals
var loading;
var sort_column; // new window or tab is always last_changed
var sort_order;  // new window or tab is always descending
var coordX;
var coordY;

// restore scroll position on submit/reload 
document.addEventListener("DOMContentLoaded", function(event) {
	var scrollpos = sessionStorage.getItem('scrollpos');
	if (scrollpos) window.scrollTo(0, scrollpos);
});

// mobile scroll position retention 
if (/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)) {
	document.addEventListener("visibilitychange", function() {
		storeScrollAndSearch();
	});
} else {
	// non-mobile scroll position retention 
	window.onbeforeunload = function(e) {
		storeScrollAndSearch();
	};
}
function storeScrollAndSearch() {
	sessionStorage.setItem('scrollpos', window.pageYOffset);
	sessionStorage.setItem('searchtxt', document.getElementById("txtInput").value);
}

// (ctl)-alt-s search hotkey
document.onkeyup = function(e) {
	var e = e || window.event; // for IE to cover IEs window event-object
	if (e.altKey && (e.which == CONSTANT_S_KEY || e.which == CONSTANT_s_KEY)) {
		document.getElementById("txtInput").focus();
		return false;
	}
}

// keep track of click position for placement of checkbox-functions grid display
document.addEventListener("click", clickPos);
function clickPos(event) {
	coordX = event.clientX;
	coordY = event.clientY;
}

// page load functions
window.addEventListener('DOMContentLoaded', (event) => {
	load_functions();
});

function load_functions() {
	// loading
	loading = true;
	// retain checked items
	checkChange();
	// retrieve saved sorting
	getSort();
	// sort if not default
	sortTable(sort_column);
	// search
	if (isSessionStorageSupported()) {
		// retrieve search
		if (sessionStorage.getItem("searchtxt") != null) {
			document.getElementById("txtInput").value = sessionStorage.getItem("searchtxt");
			tblSearch(this);
		}
	}
}

// sorting
function sortTable(n) {
	var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0,
		sortimgs, sortableimgs;
	table = document.getElementById("watch-table");
	switching = true;
	//Set the sorting direction, either default 9, 1 or saved
	if (loading) {
		getSort();
		dir = (sort_order == 0) ? "asc" : "desc";
		loading = false;
	} else {
		dir = "asc";
	}
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
			if (!isNaN(x)) { // handle numeric columns
				x = parseFloat(x);
				y = parseFloat(y);
			}
			if (n == 1) { // handle play/pause column
				x = rows[i].getElementsByTagName("TD")[n].getElementsByTagName("img")[0].src;
				y = rows[i + 1].getElementsByTagName("TD")[n].getElementsByTagName("img")[0].src;
			}
			/*check if the two rows should switch place,
			based on the direction, asc or desc:*/
			if (dir == "asc") {
				if (x > y) {
					//if so, mark as a switch and break the loop:
					shouldSwitch = true;
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
			switchcount++;
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
	for (i = 0; i < sortimgs.length; i++) {
		sortimgs[i].style.display = "none";
	}
	// show current asc/desc sort arrow and set sort_order var
	if (dir == "asc") {
		document.getElementById("sort-" + n + "a").style.display = "";
	} else {
		document.getElementById("sort-" + n + "d").style.display = "";
	}
	// show all sortable indicators
	sortableimgs = document.querySelectorAll('[id^="sortable-"]');
	for (i = 0; i < sortableimgs.length; i++) {
		sortableimgs[i].style.display = "";
	}
	// hide sortable indicator from current column
	document.getElementById("sortable-" + n).style.display = "none";
	// save sorting
	sessionStorage.setItem("sort_column", n);
	sessionStorage.setItem("sort_order", (dir == "asc") ? 0 : 1);
	// restripe rows
	restripe();
}

// check/uncheck all checkboxes
function checkAll(e) {
	var i;
	var checkboxes = document.getElementsByName('check');
	var checkboxFunctions = document.getElementById('checkbox-functions');
	if (e.checked) {
		for (i = 0; i < checkboxes.length; i++) {
			checkboxes[i].checked = true;
		}
		checkboxFunctions.style.left = coordX + 25 + "px";
		checkboxFunctions.style.top = coordY + "px";
		checkboxFunctions.style.display = "";
	} else {
		for (i = 0; i < checkboxes.length; i++) {
			checkboxes[i].checked = false;
		}
		checkboxFunctions.style.display = "none";
	}
}

// check/uncheck checkall checkbox if all other checkboxes are checked/unchecked
function checkChange() {
	var i;
	var totalCheckbox = document.querySelectorAll('input[name="check"]').length;
	var totalChecked = document.querySelectorAll('input[name="check"]:checked').length;
	var checkboxFunctions = document.getElementById('checkbox-functions'); //document.querySelectorAll('[id=checkbox-functions]');
	if (totalCheckbox == totalChecked) {
		document.getElementsByName("showhide")[0].checked = true;
	} else {
		document.getElementsByName("showhide")[0].checked = false;
	}
	if (totalChecked > 0) {
		checkboxFunctions.style.display = "";
		checkboxFunctions.style.left = coordX + 25 + "px";
		if ( coordY > ( window.innerHeight - checkboxFunctions.offsetHeight) ) {
			checkboxFunctions.style.top = (window.innerHeight - checkboxFunctions.offsetHeight) + "px";
		}
		else {
			checkboxFunctions.style.top = coordY + "px";
		}
	} else {
		checkboxFunctions.style.display = "none";
	}
}

// search watches in Title column
function tblSearch(evt) {
	var code = evt.charCode || evt.keyCode;
	if (code == CONSTANT_ESCAPE_KEY) {
		document.getElementById("txtInput").value = '';
	}
	var input, filter, table, tr, td, i, txtValue;
	input = document.getElementById("txtInput");
	filter = input.value.toUpperCase();
	table = document.getElementById("watch-table");
	tr = table.getElementsByTagName("tr");
	for (i = 1; i < tr.length; i++) { // skip header
		td = tr[i].getElementsByTagName("td")[3]; // col 3 is the hidden title/url column
		if (td) {
			txtValue = td.textContent || td.innerText;
			if (txtValue.toUpperCase().indexOf(filter) > -1) {
				tr[i].style.display = "";
			} else {
				tr[i].style.display = "none";
			}
		}
	}
	// restripe rows
	restripe();
	if (code == CONSTANT_ESCAPE_KEY) {
		document.getElementById("watch-table-wrapper").focus();
	}
}

// restripe after searching or sorting
function restripe() {
	var i, visrows = [];
	var table = document.getElementById("watch-table");
	var rows = table.getElementsByTagName("tr");

	for (i = 1; i < rows.length; i++) { // skip header
		if (rows[i].style.display !== "none") {
			visrows.push(rows[i]);
		}
	}
	for (i = 0; i < visrows.length; i++) {
		var row = visrows[i];
		if (i % 2 == 0) {
			row.classList.remove('pure-table-odd');
			row.classList.add('pure-table-even');
		} else {
			row.classList.remove('pure-table-even');
			row.classList.add('pure-table-odd');
		}
		var cells = row.getElementsByTagName("td");
		for (var j = 0; j < cells.length; j++) {
			if (i % 2 == 0) {
				cells[j].style.background = "#f2f2f2";
			} else {
				cells[j].style.background = "#ffffff";
			}
		}
		// uncomment to renumber rows ascending:    var cells = row.getElementsByTagName("td");
		// uncomment to renumber rows ascending:    cells[0].innerText = i+1;
	}
}

// get checked or all uuids
function getChecked(items) {
	var i, checkedArr, uuids = '';

	if (items === undefined) {
		checkedArr = document.querySelectorAll('input[name="check"]:checked');
	} else {
		checkedArr = document.querySelectorAll('input[name="check"]');
	}
	if (checkedArr.length > 0) {
		let output = [];
		for (i = 0; i < checkedArr.length; i++) {
			output.push(checkedArr[i].parentNode.parentNode.getAttribute("id"));
		}
		for (i = 0; i < checkedArr.length; i++) {
			if (i < checkedArr.length - 1) {
				uuids += output[i] + ",";
			} else {
				uuids += output[i];
			}
		}
	}
	return uuids;
}

// process selected watches 
function processChecked(func, tag) {
	var uuids, result;

	if (func == 'mark_all_notviewed') {
		uuids = getChecked('all');
	} else {
		uuids = getChecked();
	}
	// confirm if deleting
	if (func == 'delete_selected' && uuids.length > 0) {
		result = confirm('Deletions cannot be undone.\n\nAre you sure you want to continue?');
		if (result == false) {
			return;
		}
	}
	// href locations
	var currenturl = window.location;
	var posturl = location.protocol + '//' + location.host + '/api/process-selected';
	// posting vars
	const XHR = new XMLHttpRequest(),
		FD = new FormData();
	// fill form data
	FD.append('func', func);
	FD.append('tag', tag);
	FD.append('uuids', uuids);
	// success
	XHR.addEventListener('load', function(event) {
		window.location = currenturl;
	});
	// error
	XHR.addEventListener(' error', function(event) {
		alert('Error posting request.');
	});
	// set up request
	XHR.open('POST', posturl);
	// send
	XHR.send(FD);
}

function clearSearch() {
	document.getElementById("txtInput").value = '';
	tblSearch(CONSTANT_ESCAPE_KEY);
}

function isSessionStorageSupported() {
	var storage = window.sessionStorage;
	try {
		storage.setItem('test', 'test');
		storage.removeItem('test');
		return true;
	} catch (e) {
		return false;
	}
}

function getSort() {
	if (isSessionStorageSupported()) {
		// retrieve sort settings if set
		if (sessionStorage.getItem("sort_column") != null) {
			sort_column = sessionStorage.getItem("sort_column");
			sort_order = sessionStorage.getItem("sort_order");
		} else {
			sort_column = 7; // last changed
			sort_order = 1; // desc
			//alert("Your web browser does not support retaining sorting and page position.");
		}
	}
}