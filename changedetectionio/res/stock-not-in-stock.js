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
    'no disponible temporalmente',
    'no longer in stock',
    'no tickets available',
    'not available',
    'not currently available',
    'not in stock',
    'notify me when available',
    'não estamos a aceitar encomendas',
    'out of stock',
    'out-of-stock',
    'produkt niedostępny',
    'sold out',
    'sold-out',
    'temporarily out of stock',
    'temporarily unavailable',
    'tickets unavailable',
    'tijdelijk uitverkocht',
    'unavailable tickets',
    'we do not currently have an estimate of when this product will be back in stock.',
    'zur zeit nicht an lager',
    '品切れ',
    '已售完',
    '품절'
  ];


  const negateOutOfStockRegexs = [
      '[0-9] in stock'
  ]
  var negateOutOfStockRegexs_r = [];
  for (let i = 0; i < negateOutOfStockRegexs.length; i++) {
    negateOutOfStockRegexs_r.push(new RegExp(negateOutOfStockRegexs[0], 'g'));
  }

  const elementsToScan = Array.from(document.getElementsByTagName('*'));
  // Removed in #2039
  //const elementsWithZeroChildren = Array.from(document.getElementsByTagName('*')).filter(element => element.children.length === 0);
  var elementText ="";

  // REGEXS THAT REALLY MEAN IT'S IN STOCK
  for (let i = elementsToScan.length - 1; i >= 0; i--) {
    const element = elementsToScan[i];
    if (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0) {
      elementText="";
      if (element.tagName.toLowerCase() === "input") {
        elementText = element.value.toLowerCase();
      } else {
        elementText = element.textContent.toLowerCase();
      }

      if (elementText.length) {
        // try which ones could mean its in stock
        for (let i = 0; i < negateOutOfStockRegexs.length; i++) {
          if (negateOutOfStockRegexs_r[i].test(elementText)) {
            return 'Possibly in stock';
          }
        }
      }
    }
  }

  // OTHER STUFF THAT COULD BE THAT IT'S OUT OF STOCK
  for (let i = elementsToScan.length - 1; i >= 0; i--) {
    const element = elementsToScan[i];
    if (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0) {
      elementText="";
      if (element.tagName.toLowerCase() === "input") {
        elementText = element.value.toLowerCase();
      } else {
        elementText = element.textContent.toLowerCase();
      }

      if (elementText.length) {
        // and these mean its out of stock
        for (const outOfStockText of outOfStockTexts) {
          if (elementText.includes(outOfStockText)) {
            return elementText; // item is out of stock
          }
        }
      }
    }
  }

  return 'Possibly in stock'; // possibly in stock, cant decide otherwise.
}

// returns the element text that makes it think it's out of stock
return isItemInStock();
