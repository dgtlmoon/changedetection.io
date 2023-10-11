$(document).ready(function () {
    var a = document.getElementById("a");
    var b = document.getElementById("b");
    var result = document.getElementById("result");
    var inputs = document.getElementsByClassName("change");
    inputs.current = 0;

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

        // Jump at start
        inputs.current = 0;
        next_diff();
    }

    $('.needs-localtime').each(function () {
        for (var option of this.options) {
            var dateObject = new Date(option.value * 1000);
            option.label = dateObject.toLocaleString(undefined, {dateStyle: "full", timeStyle: "medium"});
        }
    })
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


    function next_diff() {
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
    }

});

