$(document).ready(function () {

    var inputs;

    $('#jump-next-diff').click(function () {

        var element = inputs[inputs.current];
        var headerOffset = 80;
        var elementPosition = element.getBoundingClientRect().top;
        var offsetPosition = elementPosition - headerOffset + window.scrollY;

        window.scrollTo({
            top: offsetPosition,
            behavior: "smooth",
        });

        inputs.current++;
        if (inputs.current >= inputs.length) {
            inputs.current = 0;
        }
    });

    function changed() {
        //$('#jump-next-diff').click();
    }

});

