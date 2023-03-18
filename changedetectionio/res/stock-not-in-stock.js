function isItemInStock() {
  // @todo Pass these in so the same list can be used in non-JS fetchers
  const outOfStockTexts = [
    'out of stock',
    'backordered',
    'coming soon',
    'currently unavailable',
    'not in stock',
    'sold out',
    'temporarily unavailable',
    'temporarily out of stock',
    'aktuell nicht auf lager',
    'nicht lieferbar',
    'zur zeit nicht an lager',
    '0 in stock',
    'available for back order',
    'produkt niedostępny',
    'nicht zur Verfügung',
    'we do not currently have an estimate of when this product will be back in stock.'
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