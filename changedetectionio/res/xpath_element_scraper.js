// Copyright (C) 2021 Leigh Morresi (dgtlmoon@gmail.com)
// All rights reserved.

// @file Scrape the page looking for elements of concern (%ELEMENTS%)
// http://matatk.agrip.org.uk/tests/position-and-width/
// https://stackoverflow.com/questions/26813480/when-is-element-getboundingclientrect-guaranteed-to-be-updated-accurate
//
// Some pages like https://www.londonstockexchange.com/stock/NCCL/ncondezi-energy-limited/analysis
// will automatically force a scroll somewhere, so include the position offset
// Lets hope the position doesnt change while we iterate the bbox's, but this is better than nothing
var scroll_y = 0;
try {
    scroll_y = +document.documentElement.scrollTop || document.body.scrollTop
} catch (e) {
    console.log(e);
}



// Include the getXpath script directly, easier than fetching
function getxpath(e) {
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

const findUpTag = (el) => {
    let r = el
    chained_css = [];
    depth = 0;

    //  Strategy 1: If it's an input, with name, and there's only one, prefer that
    if (el.name !== undefined && el.name.length) {
        var proposed = el.tagName + "[name=" + el.name + "]";
        var proposed_element = window.document.querySelectorAll(proposed);
        if (proposed_element.length) {
            if (proposed_element.length === 1) {
                return proposed;
            } else {
                // Some sites change ID but name= stays the same, we can hit it if we know the index
                // Find all the elements that match and work out the input[n]
                var n = Array.from(proposed_element).indexOf(el);
                // Return a Playwright selector for nthinput[name=zipcode]
                return proposed + " >> nth=" + n;
            }
        }
    }

    // Strategy 2: Keep going up until we hit an ID tag, imagine it's like  #list-widget div h4
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
// %ELEMENTS% replaced at injection time because different interfaces use it with different settings
var elements = window.document.querySelectorAll("%ELEMENTS%");
var size_pos = [];
// after page fetch, inject this JS
// build a map of all elements and their positions (maybe that only include text?)
var bbox;
for (var i = 0; i < elements.length; i++) {
    bbox = elements[i].getBoundingClientRect();

    // Exclude items that are not interactable or visible
    if(elements[i].style.opacity === "0") {
        continue
    }
    if(elements[i].style.display === "none" || elements[i].style.pointerEvents === "none" ) {
        continue
    }

    // Skip really small ones, and where width or height ==0
    if (bbox['width'] * bbox['height'] < 100) {
        continue;
    }

    // Don't include elements that are offset from canvas
    if (bbox['top']+scroll_y < 0 || bbox['left'] < 0) {
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
            xpath_result = getxpath(elements[i]);
        } catch (e) {
            console.log(e);
            continue;
        }
    }

    if (window.getComputedStyle(elements[i]).visibility === "hidden") {
        continue;
    }

    // @todo Possible to ONLY list where it's clickable to save JSON xfer size
    size_pos.push({
        xpath: xpath_result,
        width: Math.round(bbox['width']),
        height: Math.round(bbox['height']),
        left: Math.floor(bbox['left']),
        top: Math.floor(bbox['top'])+scroll_y,
        tagName: (elements[i].tagName) ? elements[i].tagName.toLowerCase() : '',
        tagtype: (elements[i].tagName == 'INPUT' && elements[i].type) ? elements[i].type.toLowerCase() : '',
        isClickable: (elements[i].onclick) || window.getComputedStyle(elements[i]).cursor == "pointer"
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
            if (f.startsWith('/') || f.startsWith('xpath')) {
                var qry_f = f.replace(/xpath(:|\d:)/, '')
                console.log("[xpath] Scanning for included filter " + qry_f)
                q = document.evaluate(qry_f, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            } else {
                console.log("[css] Scanning for included filter " + f)
                q = document.querySelector(f);
            }
        } catch (e) {
            // Maybe catch DOMException and alert?
            console.log("xpath_element_scraper: Exception selecting element from filter "+f);
            console.log(e);
        }

        if (q) {
            // Try to resolve //something/text() back to its /something so we can atleast get the bounding box
            try {
                if (typeof q.nodeName == 'string' && q.nodeName === '#text') {
                    q = q.parentElement
                }
            } catch (e) {
                console.log(e)
                console.log("xpath_element_scraper: #text resolver")
            }

            // #1231 - IN the case XPath attribute filter is applied, we will have to traverse up and find the element.
            if (typeof q.getBoundingClientRect == 'function') {
                bbox = q.getBoundingClientRect();
                console.log("xpath_element_scraper: Got filter element, scroll from top was " + scroll_y)
            } else {
                try {
                    // Try and see we can find its ownerElement
                    bbox = q.ownerElement.getBoundingClientRect();
                    console.log("xpath_element_scraper: Got filter by ownerElement element, scroll from top was " + scroll_y)
                } catch (e) {
                    console.log(e)
                    console.log("xpath_element_scraper: error looking up q.ownerElement")
                }
            }
        }
        
        if(!q) {
            console.log("xpath_element_scraper: filter element " + f + " was not found");
        }

        if (bbox && bbox['width'] > 0 && bbox['height'] > 0) {
            size_pos.push({
                xpath: f,
                width: parseInt(bbox['width']),
                height: parseInt(bbox['height']),
                left: parseInt(bbox['left']),
                top: parseInt(bbox['top'])+scroll_y
            });
        }
    }
}

// Sort the elements so we find the smallest one first, in other words, we find the smallest one matching in that area
// so that we dont select the wrapping element by mistake and be unable to select what we want
size_pos.sort((a, b) => (a.width*a.height > b.width*b.height) ? 1 : -1)

// Window.width required for proper scaling in the frontend
return {'size_pos': size_pos, 'browser_width': window.innerWidth};
