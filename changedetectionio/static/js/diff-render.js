var a = document.getElementById('a');
var b = document.getElementById('b');
var result = document.getElementById('result');

function changed() {
    // https://github.com/kpdecker/jsdiff/issues/389
    // I would love to use `{ignoreWhitespace: true}` here but it breaks the formatting
    options = {ignoreWhitespace: document.getElementById('ignoreWhitespace').checked};

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
            node = document.createElement('del');
            node.classList.add("change");
            node.appendChild(document.createTextNode(diff[i].value));

        } else if (diff[i].added) {
            node = document.createElement('ins');
            node.classList.add("change");
            node.appendChild(document.createTextNode(diff[i].value));
        } else {
            node = document.createTextNode(diff[i].value);
        }
        fragment.appendChild(node);
    }

    result.textContent = '';
    result.appendChild(fragment);

    // Jump at start
    inputs.current = 0;
    next_diff();
}

window.onload = function () {


    /* Convert what is options from UTC time.time() to local browser time */
    var diffList = document.getElementById("diff-version");
    if (typeof (diffList) != 'undefined' && diffList != null) {
        for (var option of diffList.options) {
            var dateObject = new Date(option.value * 1000);
            option.label = dateObject.toLocaleString();
        }
    }

    /* Set current version date as local time in the browser also */
    var current_v = document.getElementById("current-v-date");
    var dateObject = new Date(newest_version_timestamp*1000);
    current_v.innerHTML = dateObject.toLocaleString();
    onDiffTypeChange(document.querySelector('#settings [name="diff_type"]:checked'));
    changed();
};

a.onpaste = a.onchange =
    b.onpaste = b.onchange = changed;

if ('oninput' in a) {
    a.oninput = b.oninput = changed;
} else {
    a.onkeyup = b.onkeyup = changed;
}

function onDiffTypeChange(radio) {
    window.diffType = radio.value;
// Not necessary
//	document.title = "Diff " + radio.value.slice(4);
}

var radio = document.getElementsByName('diff_type');
for (var i = 0; i < radio.length; i++) {
    radio[i].onchange = function (e) {
        onDiffTypeChange(e.target);
        changed();
    }
}

document.getElementById('ignoreWhitespace').onchange = function (e) {
    changed();
}


var inputs = document.getElementsByClassName('change');
inputs.current = 0;


function next_diff() {

    var element = inputs[inputs.current];
    var headerOffset = 80;
    var elementPosition = element.getBoundingClientRect().top;
    var offsetPosition = elementPosition - headerOffset + window.scrollY;

    window.scrollTo({
        top: offsetPosition,
        behavior: "smooth"
    });

    inputs.current++;
    if (inputs.current >= inputs.length) {
        inputs.current = 0;
    }
}
