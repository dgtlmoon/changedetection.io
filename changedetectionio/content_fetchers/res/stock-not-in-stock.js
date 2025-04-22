async () => {

    function isItemInStock() {
        // @todo Pass these in so the same list can be used in non-JS fetchers
        const outOfStockTexts = [
            ' أخبرني عندما يتوفر',
            '0 in stock',
            'actuellement indisponible',
            'agotado',
            'article épuisé',
            'artikel zurzeit vergriffen',
            'as soon as stock is available',
            'aucune offre n\'est disponible',
            'ausverkauft', // sold out
            'available for back order',
            'awaiting stock',
            'back in stock soon',
            'back-order or out of stock',
            'backordered',
            'benachrichtigt mich', // notify me
            'brak na stanie',
            'brak w magazynie',
            'coming soon',
            'currently have any tickets for this',
            'currently unavailable',
            'dieser artikel ist bald wieder verfügbar',
            'dostępne wkrótce',
            'en rupture',
            'esgotado',
            'in kürze lieferbar',
            'indisponible',
            'indisponível',
            'isn\'t in stock right now',
            'isnt in stock right now',
            'isn’t in stock right now',
            'item is no longer available',
            'let me know when it\'s available',
            'mail me when available',
            'message if back in stock',
            'mevcut değil',
            'nachricht bei',
            'nicht auf lager',
            'nicht lagernd',
            'nicht lieferbar',
            'nicht verfügbar',
            'nicht vorrätig',
            'nicht zur verfügung',
            'nie znaleziono produktów',
            'niet beschikbaar',
            'niet leverbaar',
            'niet op voorraad',
            'no disponible',
            'no featured offers available',
            'no longer in stock',
            'no tickets available',
            'non disponibile',
            'non disponible',
            'not available',
            'not currently available',
            'not in stock',
            'notify me when available',
            'notify me',
            'notify when available',
            'não disponível',
            'não estamos a aceitar encomendas',
            'out of stock',
            'out-of-stock',
            'plus disponible',
            'prodotto esaurito',
            'produkt niedostępny',
            'rupture',
            'sold out',
            'sold-out',
            'stok habis',
            'stok kosong',
            'stok varian ini habis',
            'stokta yok',
            'temporarily out of stock',
            'temporarily unavailable',
            'there were no search results for',
            'this item is currently unavailable',
            'tickets unavailable',
            'tidak dijual',
            'tidak tersedia',
            'tijdelijk uitverkocht',
            'tiket tidak tersedia',
            'tükendi',
            'unavailable nearby',
            'unavailable tickets',
            'vergriffen',
            'vorbestellen',
            'vorbestellung ist bald möglich',
            'we couldn\'t find any products that match',
            'we do not currently have an estimate of when this product will be back in stock.',
            'we don\'t currently have any',
            'we don\'t know when or if this item will be back in stock.',
            'we were not able to find a match',
            'when this arrives in stock',
            'when this item is available to order',
            'zur zeit nicht an lager',
            'épuisé',
            '品切れ',
            '已售',
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

        const negateOutOfStockRegex = new RegExp('^([0-9] in stock|add to cart|in stock)', 'ig');

        // The out-of-stock or in-stock-text is generally always above-the-fold
        // and often below-the-fold is a list of related products that may or may not contain trigger text
        // so it's good to filter to just the 'above the fold' elements
        // and it should be atleast 100px from the top to ignore items in the toolbar, sometimes menu items like "Coming soon" exist


// @todo - if it's SVG or IMG, go into image diff mode

        function collectVisibleElements(parent, visibleElements) {
            if (!parent) return; // Base case: if parent is null or undefined, return

            // Add the parent itself to the visible elements array if it's of the specified types
            visibleElements.push(parent);

            // Iterate over the parent's children
            const children = parent.children;
            for (let i = 0; i < children.length; i++) {
                const child = children[i];
                if (
                    child.nodeType === Node.ELEMENT_NODE &&
                    window.getComputedStyle(child).display !== 'none' &&
                    window.getComputedStyle(child).visibility !== 'hidden' &&
                    child.offsetWidth >= 0 &&
                    child.offsetHeight >= 0 &&
                    window.getComputedStyle(child).contentVisibility !== 'hidden'
                ) {
                    // If the child is an element and is visible, recursively collect visible elements
                    collectVisibleElements(child, visibleElements);
                }
            }
        }

        const elementsToScan = [];
        collectVisibleElements(document.body, elementsToScan);

        var elementText = "";

        // REGEXS THAT REALLY MEAN IT'S IN STOCK
        for (let i = elementsToScan.length - 1; i >= 0; i--) {
            const element = elementsToScan[i];

            // outside the 'fold' or some weird text in the heading area
            // .getBoundingClientRect() was causing a crash in chrome 119, can only be run on contentVisibility != hidden
            if (element.getBoundingClientRect().top + window.scrollY >= vh || element.getBoundingClientRect().top + window.scrollY <= 100) {
                continue
            }

            elementText = "";
            try {
                if (element.tagName.toLowerCase() === "input") {
                    elementText = element.value.toLowerCase().trim();
                } else {
                    elementText = getElementBaseText(element);
                }
            } catch (e) {
                console.warn('stock-not-in-stock.js scraper - handling element for gettext failed', e);
            }

            if (elementText.length) {
                // try which ones could mean its in stock
                if (negateOutOfStockRegex.test(elementText) && !elementText.includes('(0 products)')) {
                    console.log(`Negating/overriding 'Out of Stock' back to "Possibly in stock" found "${elementText}"`)
                    return 'Possibly in stock';
                }
            }
        }

        // OTHER STUFF THAT COULD BE THAT IT'S OUT OF STOCK
        for (let i = elementsToScan.length - 1; i >= 0; i--) {
            const element = elementsToScan[i];
            // outside the 'fold' or some weird text in the heading area
            // .getBoundingClientRect() was causing a crash in chrome 119, can only be run on contentVisibility != hidden
            // Note: theres also an automated test that places the 'out of stock' text fairly low down
            if (element.getBoundingClientRect().top + window.scrollY >= vh + 250 || element.getBoundingClientRect().top + window.scrollY <= 100) {
                continue
            }
            elementText = "";
            if (element.tagName.toLowerCase() === "input") {
                elementText = element.value.toLowerCase().trim();
            } else {
                elementText = getElementBaseText(element);
            }

            if (elementText.length) {
                // and these mean its out of stock
                for (const outOfStockText of outOfStockTexts) {
                    if (elementText.includes(outOfStockText)) {
                        console.log(`Selected 'Out of Stock' - found text "${outOfStockText}" - "${elementText}" - offset top ${element.getBoundingClientRect().top}, page height is ${vh}`)
                        return outOfStockText; // item is out of stock
                    }
                }
            }
        }

        console.log(`Returning 'Possibly in stock' - cant' find any useful matching text`)
        return 'Possibly in stock'; // possibly in stock, cant decide otherwise.
    }

// returns the element text that makes it think it's out of stock
    return isItemInStock().trim()
}
