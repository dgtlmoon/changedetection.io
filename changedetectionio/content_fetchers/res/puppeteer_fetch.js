module.exports = async ({page, context}) => {

    var {
        url,
        execute_js,
        user_agent,
        extra_wait_ms,
        req_headers,
        include_filters,
        xpath_element_js,
        screenshot_quality,
        proxy_username,
        proxy_password,
        disk_cache_dir,
        no_cache_list,
        block_url_list,
    } = context;

    await page.setBypassCSP(true)
    await page.setExtraHTTPHeaders(req_headers);
    var total_size = 0;

    if (user_agent) {
        await page.setUserAgent(user_agent);
    }
    // https://ourcodeworld.com/articles/read/1106/how-to-solve-puppeteer-timeouterror-navigation-timeout-of-30000-ms-exceeded

    await page.setDefaultNavigationTimeout(0);

    if (proxy_username) {
        // Setting Proxy-Authentication header is deprecated, and doing so can trigger header change errors from Puppeteer
        // https://github.com/puppeteer/puppeteer/issues/676 ?
        // https://help.brightdata.com/hc/en-us/articles/12632549957649-Proxy-Manager-How-to-Guides#h_01HAKWR4Q0AFS8RZTNYWRDFJC2
        // https://cri.dev/posts/2020-03-30-How-to-solve-Puppeteer-Chrome-Error-ERR_INVALID_ARGUMENT/
        await page.authenticate({
            username: proxy_username,
            password: proxy_password
        });
    }

    await page.setViewport({
        width: 1024,
        height: 768,
        deviceScaleFactor: 1,
    });
    await page.setRequestInterception(true);
    await page.setCacheEnabled(false);


    await page.evaluateOnNewDocument('navigator.serviceWorker.register = () => { console.warn("Service Worker registration blocked by Playwright")}');

    await page.evaluateOnNewDocument(`
   
  const toBlob = HTMLCanvasElement.prototype.toBlob;
  const toDataURL = HTMLCanvasElement.prototype.toDataURL;

    HTMLCanvasElement.prototype.manipulate = function() {
    console.warn("ma");
    const {width, height} = this;
    const context = this.getContext('2d');
    var dt = new Date();
    
    const shift = {
      'r': dt.getDay()-3,
      'g': dt.getDay()-3,
      'b': dt.getDay()-3
    };
    console.log(shift);
    const matt = context.getImageData(0, 0, width, height);
    for (let i = 0; i < height; i += Math.max(1, parseInt(height / 10))) {
      for (let j = 0; j < width; j += Math.max(1, parseInt(width / 10))) {
        const n = ((i * (width * 4)) + (j * 4));
        matt.data[n + 0] = matt.data[n + 0] + shift.r;
        matt.data[n + 1] = matt.data[n + 1] + shift.g;
        matt.data[n + 2] = matt.data[n + 2] + shift.b;
      }
    }
    context.putImageData(matt, 0, 0);
  };

  Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', {
    value: function() {
    console.warn("toblob");
      if (true) {
        try {
          this.manipulate();
        }
        catch(e) {
          console.warn('manipulation failed', e);
        }
      }
      return toBlob.apply(this, arguments);
    }
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    value: function() {
        console.warn("todata");
      if (true) {
        try {
          this.manipulate();
        }
        catch(e) {
          console.warn('manipulation failed', e);
        }
      }
      return toDataURL.apply(this, arguments);
    }
  });


  Object.defineProperty(navigator, 'webdriver', {get: () => false});
`)

    await page.emulateTimezone('America/Chicago');

    var r = await page.goto(url, {
        waitUntil: 'load', timeout: 0
    });

// https://github.com/puppeteer/puppeteer/issues/2479#issuecomment-408263504
    if (r === null) {
        r = await page.waitForResponse(() => true);
    }

    await page.waitForTimeout(4000);
    await page.waitForTimeout(extra_wait_ms);


    if (execute_js) {
        await page.evaluate(execute_js);
        await page.waitForTimeout(200);
    }

    var xpath_data;
    var instock_data;
    try {
        // Not sure the best way here, in the future this should be a new package added to npm then run in evaluatedCode
        // (Once the old playwright is removed)
        xpath_data = await page.evaluate((include_filters) => {%xpath_scrape_code%}, include_filters);
        instock_data = await page.evaluate(() => {%instock_scrape_code%});
    } catch (e) {
        console.log(e);
    }

    // Protocol error (Page.captureScreenshot): Cannot take screenshot with 0 width can come from a proxy auth failure
    // Wrap it here (for now)

    var b64s = false;
    try {
        b64s = await page.screenshot({encoding: "base64", fullPage: true, quality: screenshot_quality, type: 'jpeg'});
    } catch (e) {
        console.log(e);
    }

    // May fail on very large pages with 'WARNING: tile memory limits exceeded, some content may not draw'
    if (!b64s) {
        // @todo after text extract, we can place some overlay text with red background to say 'croppped'
        console.error('ERROR: content-fetcher page was maybe too large for a screenshot, reverting to viewport only screenshot');
        try {
            b64s = await page.screenshot({encoding: "base64", quality: screenshot_quality, type: 'jpeg'});
        } catch (e) {
            console.log(e);
        }
    }

    var html = await page.content();
    page.close();

    return {
        data: {
            'content': html,
            'headers': r.headers(),
            'instock_data': instock_data,
            'screenshot': b64s,
            'status_code': r.status(),
            'xpath_data': xpath_data,
            'total_size': total_size
        },
        type: 'application/json',
    };
};
