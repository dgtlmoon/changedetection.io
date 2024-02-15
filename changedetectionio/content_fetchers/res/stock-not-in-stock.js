// Restock Detector
// (c) Leigh Morresi dgtlmoon@gmail.com
//
// Assumes the product is in stock to begin with, unless the following appears above the fold ;
// - outOfStockTexts appears above the fold (out of stock)
// - negateOutOfStockRegex (really is in stock)

function isItemInStock() {
    // @todo Pass these in so the same list can be used in non-JS fetchers
    const outOfStockTexts = [
        ' أخبرني عندما يتوفر',
        '0 in stock',
        'agotado',
        'article épuisé',
        'artikel zurzeit vergriffen',
        'as soon as stock is available',
        'ausverkauft', // sold out
        'available for back order',
        'back-order or out of stock',
        'backordered',
        'benachrichtigt mich', // notify me
        'brak na stanie',
        'brak w magazynie',
        'coming soon',
        'currently have any tickets for this',
        'currently unavailable',
        'dostępne wkrótce',
        'en rupture de stock',
        'ist derzeit nicht auf lager',
        'item is no longer available',
        'let me know when it\'s available',
        'message if back in stock',
        'nachricht bei',
        'nicht auf lager',
        'nicht lieferbar',
        'nicht zur verfügung',
        'niet beschikbaar',
        'niet leverbaar',
        'niet op voorraad',
        'no disponible temporalmente',
        'no longer in stock',
        'no tickets available',
        'not available',
        'not currently available',
        'not in stock',        
        'notify me when available',
        'notify when available',            
        'não estamos a aceitar encomendas',
        'out of stock',
        'out-of-stock',
        'prodotto esaurito',
        'produkt niedostępny',
        'sold out',
        'sold-out',
        'temporarily out of stock',
        'temporarily unavailable',
        'tickets unavailable',
        'tijdelijk uitverkocht',
        'unavailable tickets',
        'we do not currently have an estimate of when this product will be back in stock.',
        'we don\'t know when or if this item will be back in stock.',
        'zur zeit nicht an lager',
        '品切れ',
        '已售完',
        '품절'
    ];

    const vh = Math.max(document.documentElement.clientHeight || 0, window.innerHeight || 0);
    function getElementBaseText(element) {
        // .textContent can include text from children which may give the wrong results
        // scan only immediate TEXT_NODEs, which will be a child of the element
        var text = "";
        for (var i = 0; i < element.childNodes.length; ++i)
            if (element.childNodes[i].nodeType === Node.TEXT_NODE)
                text += element.childNodes[i].textContent;
        return text.toLowerCase().trim();
    }

    const negateOutOfStockRegex = new RegExp('([0-9] in stock|add to cart)', 'ig');

    // The out-of-stock or in-stock-text is generally always above-the-fold
    // and often below-the-fold is a list of related products that may or may not contain trigger text
    // so it's good to filter to just the 'above the fold' elements
    // and it should be atleast 100px from the top to ignore items in the toolbar, sometimes menu items like "Coming soon" exist
    const elementsToScan = Array.from(document.getElementsByTagName('*')).filter(element => element.getBoundingClientRect().top + window.scrollY <= vh && element.getBoundingClientRect().top + window.scrollY >= 100);

    var elementText = "";

    // REGEXS THAT REALLY MEAN IT'S IN STOCK
    for (let i = elementsToScan.length - 1; i >= 0; i--) {
        const element = elementsToScan[i];
        elementText = "";
        if (element.tagName.toLowerCase() === "input") {
            elementText = element.value.toLowerCase();
        } else {
            elementText = getElementBaseText(element);
        }

        if (elementText.length) {
            // try which ones could mean its in stock
            if (negateOutOfStockRegex.test(elementText)) {
                return 'Possibly in stock';
            }
        }
    }

    // OTHER STUFF THAT COULD BE THAT IT'S OUT OF STOCK
    for (let i = elementsToScan.length - 1; i >= 0; i--) {
        const element = elementsToScan[i];
        if (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0) {
            elementText = "";
            if (element.tagName.toLowerCase() === "input") {
                elementText = element.value.toLowerCase();
            } else {
                elementText = getElementBaseText(element);
            }

            if (elementText.length) {
                // and these mean its out of stock
                for (const outOfStockText of outOfStockTexts) {
                    if (elementText.includes(outOfStockText)) {
                        return outOfStockText; // item is out of stock
                    }
                }
            }
        }
    }

    return 'Possibly in stock'; // possibly in stock, cant decide otherwise.
}

// returns the element text that makes it think it's out of stock
return isItemInStock().trim()

