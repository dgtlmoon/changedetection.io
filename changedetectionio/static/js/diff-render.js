$(document).ready(function () {
    var a = document.getElementById("a");
    var b = document.getElementById("b");
    var result = document.getElementById("result");
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
        // https://github.com/kpdecker/jsdiff/issues/389
        // I would love to use `{ignoreWhitespace: true}` here but it breaks the formatting
        options = {
            ignoreWhitespace: document.getElementById("ignoreWhitespace").checked,
        };

        var diff = Diff[window.diffType](a.textContent, b.textContent, options);
        var fragment = document.createDocumentFragment();
        for (var i = 0; i < diff.length; i++) {
            if (diff[i].added && diff[i + 1] && diff[i + 1].removed) {
                var swap = diff[i];
                diff[i] = diff[i + 1];
                diff[i + 1] = swap;
            }

            var node;
            if (diff[i].removed) {
                node = document.createElement("del");
                node.classList.add("change");
                const wrapper = node.appendChild(document.createElement("span"));
                wrapper.appendChild(document.createTextNode(diff[i].value));
            } else if (diff[i].added) {
                node = document.createElement("ins");
                node.classList.add("change");
                const wrapper = node.appendChild(document.createElement("span"));
                wrapper.appendChild(document.createTextNode(diff[i].value));
            } else {
                node = document.createTextNode(diff[i].value);
            }
            fragment.appendChild(node);
        }

        result.textContent = "";
        result.appendChild(fragment);

        // For nice mouse-over hover/title information
        const removed_current_option = $('#diff-version option:selected')
        if (removed_current_option) {
            $('del').each(function () {
                $(this).prop('title', 'Removed '+removed_current_option[0].label);
            });
        }
        const inserted_current_option = $('#current-version option:selected')
        if (removed_current_option) {
            $('ins').each(function () {
                $(this).prop('title', 'Inserted '+inserted_current_option[0].label);
            });
        }
        // Set the list of possible differences to jump to
        inputs = document.querySelectorAll('#diff-ui .change')
        // Set the "current" diff pointer
        inputs.current = 0;
        // Goto diff
        $('#jump-next-diff').click();
    }


    onDiffTypeChange(
        document.querySelector('#settings [name="diff_type"]:checked'),
    );
    changed();

    a.onpaste = a.onchange = b.onpaste = b.onchange = changed;

    if ("oninput" in a) {
        a.oninput = b.oninput = changed;
    } else {
        a.onkeyup = b.onkeyup = changed;
    }

    function onDiffTypeChange(radio) {
        window.diffType = radio.value;
        // Not necessary
        //	document.title = "Diff " + radio.value.slice(4);
    }

    var radio = document.getElementsByName("diff_type");
    for (var i = 0; i < radio.length; i++) {
        radio[i].onchange = function (e) {
            onDiffTypeChange(e.target);
            changed();
        };
    }

    document.getElementById("ignoreWhitespace").onchange = function (e) {
        changed();
    };

});

