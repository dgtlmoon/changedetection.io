(async () => {
  const links = Array.from(document.querySelectorAll(
    'link[rel~="apple-touch-icon"], link[rel~="icon"]'
  ));

  const icons = links.map(link => {
    const sizesStr = link.getAttribute('sizes');
    let size = 0;
    if (sizesStr) {
      const [w] = sizesStr.split('x').map(Number);
      if (!isNaN(w)) size = w;
    } else {
      size = 16;
    }
    return {
      size,
      rel: link.getAttribute('rel'),
      href: link.href
    };
  });

  // If no icons found, add fallback favicon.ico
  if (icons.length === 0) {
    icons.push({
      size: 16,
      rel: 'icon',
      href: '/favicon.ico'
    });
  }

  // sort preference
  icons.sort((a, b) => {
    const isAppleA = /apple-touch-icon/.test(a.rel);
    const isAppleB = /apple-touch-icon/.test(b.rel);
    if (isAppleA && !isAppleB) return -1;
    if (!isAppleA && isAppleB) return 1;
    return b.size - a.size;
  });

  const timeoutMs = 2000;

  for (const icon of icons) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), timeoutMs);

      const resp = await fetch(icon.href, {
        signal: controller.signal,
        redirect: 'follow'
      });

      clearTimeout(timeout);

      if (!resp.ok) {
        continue;
      }

      const blob = await resp.blob();

      // Convert blob to base64
      const reader = new FileReader();
      return await new Promise(resolve => {
        reader.onloadend = () => {
          resolve({
            url: icon.href,
            base64: reader.result.split(",")[1]
          });
        };
        reader.readAsDataURL(blob);
      });

    } catch (e) {
      continue;
    }
  }

  // nothing found
  return null;
})();
