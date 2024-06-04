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
    if (disk_cache_dir) {
        console.log(">>>>>>>>>>>>>>> LOCAL DISK CACHE ENABLED <<<<<<<<<<<<<<<<<<<<<");
    }
    const fs = require('fs');
    const crypto = require('crypto');

    function file_is_expired(file_path) {
        if (!fs.existsSync(file_path)) {
            return true;
        }
        var stats = fs.statSync(file_path);
        const now_date = new Date();
        const expire_seconds = 300;
        if ((now_date / 1000) - (stats.mtime.getTime() / 1000) > expire_seconds) {
            console.log("CACHE EXPIRED: " + file_path);
            return true;
        }
        return false;

    }

    page.on('request', async (request) => {
        // General blocking of requests that waste traffic
        if (block_url_list.some(substring => request.url().toLowerCase().includes(substring))) return request.abort();

        if (disk_cache_dir) {
            const url = request.url();
            const key = crypto.createHash('md5').update(url).digest("hex");
            const dir_path = disk_cache_dir + key.slice(0, 1) + '/' + key.slice(1, 2) + '/' + key.slice(2, 3) + '/';

            // https://stackoverflow.com/questions/4482686/check-synchronously-if-file-directory-exists-in-node-js

            if (fs.existsSync(dir_path + key)) {
                console.log("* CACHE HIT , using - " + dir_path + key + " - " + url);
                const cached_data = fs.readFileSync(dir_path + key);
                // @todo headers can come from dir_path+key+".meta" json file
                request.respond({
                    status: 200,
                    //contentType: 'text/html', //@todo
                    body: cached_data
                });
                return;
            }
        }
        request.continue();
    });


    if (disk_cache_dir) {
        page.on('response', async (response) => {
            const url = response.url();
            // Basic filtering for sane responses
            if (response.request().method() != 'GET' || response.request().resourceType() == 'xhr' || response.request().resourceType() == 'document' || response.status() != 200) {
                console.log("Skipping (not useful) - Status:" + response.status() + " Method:" + response.request().method() + " ResourceType:" + response.request().resourceType() + " " + url);
                return;
            }
            if (no_cache_list.some(substring => url.toLowerCase().includes(substring))) {
                console.log("Skipping (no_cache_list) - " + url);
                return;
            }
            if (url.toLowerCase().includes('data:')) {
                console.log("Skipping (embedded-data) - " + url);
                return;
            }
            response.buffer().then(buffer => {
                if (buffer.length > 100) {
                    console.log("Cache - Saving " + response.request().method() + " - " + url + " - " + response.request().resourceType());

                    const key = crypto.createHash('md5').update(url).digest("hex");
                    const dir_path = disk_cache_dir + key.slice(0, 1) + '/' + key.slice(1, 2) + '/' + key.slice(2, 3) + '/';

                    if (!fs.existsSync(dir_path)) {
                        fs.mkdirSync(dir_path, {recursive: true})
                    }

                    if (fs.existsSync(dir_path + key)) {
                        if (file_is_expired(dir_path + key)) {
                            fs.writeFileSync(dir_path + key, buffer);
                        }
                    } else {
                        fs.writeFileSync(dir_path + key, buffer);
                    }
                }
            });
        });
    }

    const r = await page.goto(url, {
        waitUntil: 'load'
    });

    await page.waitForTimeout(1000);
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
    return {
        data: {
            'content': html,
            'headers': r.headers(),
            'instock_data': instock_data,
            'screenshot': b64s,
            'status_code': r.status(),
            'xpath_data': xpath_data
        },
        type: 'application/json',
    };
};