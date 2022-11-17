// Include the getXpath script directly, easier than fetching
!function (e, n) {
    "object" == typeof exports && "undefined" != typeof module ? module.exports = n() : "function" == typeof define && define.amd ? define(n) : (e = e || self).getXPath = n()
}(this, function () {
    return function (e) {
        var n = e;
        if (n && n.id) return '//*[@id="' + n.id + '"]';
        for (var o = []; n && Node.ELEMENT_NODE === n.nodeType;) {
            for (var i = 0, r = !1, d = n.previousSibling; d;) d.nodeType !== Node.DOCUMENT_TYPE_NODE && d.nodeName === n.nodeName && i++, d = d.previousSibling;
            for (d = n.nextSibling; d;) {
                if (d.nodeName === n.nodeName) {
                    r = !0;
                    break
                }
                d = d.nextSibling
            }
            o.push((n.prefix ? n.prefix + ":" : "") + n.localName + (i || r ? "[" + (i + 1) + "]" : "")), n = n.parentNode
        }
        return o.length ? "/" + o.reverse().join("/") : ""
    }
});


const findUpTag = (el) => {
    let r = el
    chained_css = [];
    depth = 0;

// Strategy 1: Keep going up until we hit an ID tag, imagine it's like  #list-widget div h4
    while (r.parentNode) {
        if (depth == 5) {
            break;
        }
        if ('' !== r.id) {
            chained_css.unshift("#" + CSS.escape(r.id));
            final_selector = chained_css.join(' > ');
            // Be sure theres only one, some sites have multiples of the same ID tag :-(
            if (window.document.querySelectorAll(final_selector).length == 1) {
                return final_selector;
            }
            return null;
        } else {
            chained_css.unshift(r.tagName.toLowerCase());
        }
        r = r.parentNode;
        depth += 1;
    }
    return null;
}


// @todo - if it's SVG or IMG, go into image diff mode
var elements = window.document.querySelectorAll("div,span,form,table,tbody,tr,td,a,p,ul,li,h1,h2,h3,h4, header, footer, section, article, aside, details, main, nav, section, summary");
var size_pos = [];
// after page fetch, inject this JS
// build a map of all elements and their positions (maybe that only include text?)
var bbox;
for (var i = 0; i < elements.length; i++) {
    bbox = elements[i].getBoundingClientRect();

    // forget really small ones
    if (bbox['width'] < 15 && bbox['height'] < 15) {
        continue;
    }

    // @todo the getXpath kind of sucks, it doesnt know when there is for example just one ID sometimes
    // it should not traverse when we know we can anchor off just an ID one level up etc..
    // maybe, get current class or id, keep traversing up looking for only class or id until there is just one match

    // 1st primitive - if it has class, try joining it all and select, if theres only one.. well thats us.
    xpath_result = false;

    try {
        var d = findUpTag(elements[i]);
        if (d) {
            xpath_result = d;
        }
    } catch (e) {
        console.log(e);
    }

    // You could swap it and default to getXpath and then try the smarter one
    // default back to the less intelligent one
    if (!xpath_result) {
        try {
            // I've seen on FB and eBay that this doesnt work
            // ReferenceError: getXPath is not defined at eval (eval at evaluate (:152:29), <anonymous>:67:20) at UtilityScript.evaluate (<anonymous>:159:18) at UtilityScript.<anonymous> (<anonymous>:1:44)
            xpath_result = getXPath(elements[i]);
        } catch (e) {
            console.log(e);
            continue;
        }
    }

    if (window.getComputedStyle(elements[i]).visibility === "hidden") {
        continue;
    }

    size_pos.push({
        xpath: xpath_result,
        width: Math.round(bbox['width']),
        height: Math.round(bbox['height']),
        left: Math.floor(bbox['left']),
        top: Math.floor(bbox['top'])
    });
}


// Inject the current one set in the include_filters, which may be a CSS rule
// used for displaying the current one in VisualSelector, where its not one we generated.
if (include_filters.length) {
    // Foreach filter, go and find it on the page and add it to the results so we can visualise it again
    for (const f of include_filters) {
        bbox = false;
        q = false;

        if (!f.length) {
            console.log("xpath_element_scraper: Empty filter, skipping");
            continue;
        }

        try {
            // is it xpath?
            if (f.startsWith('/') || f.startsWith('xpath:')) {
                q = document.evaluate(f.replace('xpath:', ''), document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            } else {
                q = document.querySelector(f);
            }
        } catch (e) {
            // Maybe catch DOMException and alert?
            console.log("xpath_element_scraper: Exception selecting element from filter "+f);
            console.log(e);
        }

        if (q) {
            bbox = q.getBoundingClientRect();
        } else {
            console.log("xpath_element_scraper: filter element "+f+" was not found");
        }

        if (bbox && bbox['width'] > 0 && bbox['height'] > 0) {
            size_pos.push({
                xpath: f,
                width: Math.round(bbox['width']),
                height: Math.round(bbox['height']),
                left: Math.floor(bbox['left']),
                top: Math.floor(bbox['top'])
            });
        }
    }
}

// Window.width required for proper scaling in the frontend
return {'size_pos': size_pos, 'browser_width': window.innerWidth};
