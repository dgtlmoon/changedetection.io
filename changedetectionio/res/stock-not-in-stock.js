function isItemInStock() {
  // @todo Pass these in so the same list can be used in non-JS fetchers
  const outOfStockTexts = [
    '0 in stock',
    'agotado',
    'artikel zurzeit vergriffen',
    'available for back order',
    'backordered',
    'brak w magazynie',
    'coming soon',
    'currently unavailable',
    'message if back in stock',
    'nicht auf lager',
    'nicht lieferbar',
    'nicht zur verfügung',
    'no disponible temporalmente',
    'not in stock',
    'out of stock',
    'out-of-stock',
    'produkt niedostępny',
    'sold out',
    'temporarily out of stock',
    'temporarily unavailable',
    'we do not currently have an estimate of when this product will be back in stock.',
    'zur zeit nicht an lager',
  ];

  const elementsWithZeroChildren = Array.from(document.getElementsByTagName('*')).filter(element => element.children.length === 0);
  for (let i = elementsWithZeroChildren.length - 1; i >= 0; i--) {
    const element = elementsWithZeroChildren[i];
    if (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0) {
      const elementText = element.textContent.toLowerCase();
      for (const outOfStockText of outOfStockTexts) {
        if (elementText.includes(outOfStockText)) {
          return elementText; // item is out of stock
        }
      }
    }
  }
  return 'Possibly in stock'; // possibly in stock, cant decide otherwise.
}

// returns the element text that makes it think it's out of stock
return isItemInStock();