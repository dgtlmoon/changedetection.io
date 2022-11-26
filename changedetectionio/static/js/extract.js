$(document).ready(function () {

    $('#extract').click(function (e) {
        download_csv_file();
    });

//create CSV file data in an array
    var csvFileData = [
        ['Alan Walker', 'Singer'],
        ['Cristiano Ronaldo', 'Footballer'],
        ['Saina Nehwal', 'Badminton Player'],
        ['Arijit Singh', 'Singer'],
        ['Terence Lewis', 'Dancer']
    ];

//create a user-defined function to download CSV file
    function download_csv_file() {

        //define the heading for each row of the data
        var csv = 'Name,Profession\n';

        //merge the data with CSV
        csvFileData.forEach(function (row) {
            csv += row.join(',');
            csv += "\n";
        });

        //display the created CSV data on the web browser
        document.write(csv);


        var hiddenElement = document.createElement('a');
        hiddenElement.href = 'data:text/csv;charset=utf-8,' + encodeURI(csv);
        hiddenElement.target = '_blank';
        //provide the name for the CSV file to be downloaded
        hiddenElement.download = 'Famous Personalities.csv';
        hiddenElement.click();
    }

});