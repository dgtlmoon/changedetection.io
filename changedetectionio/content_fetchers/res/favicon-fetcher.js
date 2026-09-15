(async () => {
  // Define the function inside the IIFE for console testing
  window.getFaviconAsBlob = async function() {
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
        href: link.href,
        hasSizes: !!sizesStr
      };
    });

    // If no icons found, add fallback favicon.ico
    if (icons.length === 0) {
      icons.push({
        size: 16,
        rel: 'icon',
        href: '/favicon.ico',
        hasSizes: false
      });
    }

    // sort preference: highest resolution first, then apple-touch-icon, then regular icons
    icons.sort((a, b) => {
      // First priority: actual size (highest first)
      if (a.size !== b.size) {
        return b.size - a.size;
      }

      // Second priority: apple-touch-icon over regular icon
      const isAppleA = /apple-touch-icon/.test(a.rel);
      const isAppleB = /apple-touch-icon/.test(b.rel);
      if (isAppleA && !isAppleB) return -1;
      if (!isAppleA && isAppleB) return 1;

      // Third priority: icons with no size attribute (fallback icons) last
      const hasNoSizeA = !a.hasSizes;
      const hasNoSizeB = !b.hasSizes;
      if (hasNoSizeA && !hasNoSizeB) return 1;
      if (!hasNoSizeA && hasNoSizeB) return -1;

      return 0;
    });

    // All candidates are fetched concurrently under one shared deadline.
    //
    // Sequentially, each icon got its own fresh 2s AbortController, so a site declaring
    // five <link rel="icon"> variants spent 10s+ here - inside the page, holding a browser
    // and a worker the whole time. Simply capping the total made it worse: giving up early
    // returns no icon, nothing gets saved, favicon_is_expired() stays true and the cost is
    // paid again on the very next check, forever. Fetching in parallel bounds the wall time
    // *and* still finds a working icon, so it saves and the watch stops asking.
    //
    // Measured against a page with five hanging icons, one 404 and one good one:
    //   sequential, 2s each : 10.1s, found the icon
    //   total cap only      :  3.0s, found nothing (then repeats every check)
    //   parallel + deadline :  ~3s,  found the icon
    const TOTAL_BUDGET_MS = 3000;
    // 1 MB — matches the server-side limit in bump_favicon()
    const MAX_BYTES = 1 * 1024 * 1024;

    const toBase64 = (blob) => new Promise(resolve => {
      // Always resolves. The previous version resolved only from onloadend and read
      // reader.result unguarded, so a FileReader failure threw inside the callback and left
      // the promise permanently pending - the whole favicon fetch then hung with nothing
      // bounding it, because clearTimeout had already fired.
      try {
        const reader = new FileReader();
        reader.onerror = () => resolve(null);
        reader.onloadend = () => {
          try {
            const result = reader.result;
            resolve(result ? String(result).split(',')[1] : null);
          } catch (e) {
            resolve(null);
          }
        };
        reader.readAsDataURL(blob);
      } catch (e) {
        resolve(null);
      }
    });

    const controller = new AbortController();
    const budget = setTimeout(() => controller.abort(), TOTAL_BUDGET_MS);

    const fetchOne = async (icon) => {
      try {
        // Inline data URI — no network fetch needed, data is already here
        if (icon.href.startsWith('data:')) {
          const match = icon.href.match(/^data:([^;]+);base64,([A-Za-z0-9+/=]+)$/);
          if (!match) return null;
          const mime_type = match[1];
          const base64 = match[2];
          // Rough size check: base64 is ~4/3 the binary size
          if (base64.length * 0.75 > MAX_BYTES) return null;
          return { url: icon.href, mime_type, base64 };
        }

        const resp = await fetch(icon.href, {
          signal: controller.signal,
          redirect: 'follow'
        });

        if (!resp.ok) return null;

        // Skip an oversized icon before pulling its body down the wire, where the server
        // tells us the size up front.
        const declared = parseInt(resp.headers.get('content-length') || '0', 10);
        if (declared > MAX_BYTES) return null;

        // Still covered by the shared signal: aborting errors the body stream too. The
        // previous version cleared its timer before this line, leaving a slow or
        // never-ending body read completely unguarded.
        const blob = await resp.blob();
        if (blob.size > MAX_BYTES) return null;

        const base64 = await toBase64(blob);
        if (!base64) return null;

        return { url: icon.href, mime_type: blob.type, base64 };
      } catch (e) {
        return null;
      }
    };

    try {
      const settled = await Promise.all(icons.map(fetchOne));
      // icons[] is already in preference order (largest, then apple-touch-icon), so the
      // first success in that order is the one we want - not merely the fastest to answer.
      const best = settled.find(r => r);
      if (best) return best;
    } catch (e) {
      // fall through to "nothing found"
    } finally {
      clearTimeout(budget);
    }

    // nothing found
    return null;
  };

  // Auto-execute and return result for page.evaluate()
  return await window.getFaviconAsBlob();
})();
