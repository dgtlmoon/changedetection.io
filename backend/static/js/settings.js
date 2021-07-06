window.addEventListener("load", (event) => {
  function toggleTable() {
    var x = document.getElementById("token-table");
    if (x.style.display === "table") {
      x.style.display = "none";
    } else {
      x.style.display = "table";
    }
  }
  document.getElementById("show-token-table").onclick = function() {
      toggleTable();
  }
});
