const playwright = require('playwright');

const port = parseInt(process.env.PLAYWRIGHT_PORT) || 4444;
const browserType = process.env.PLAYWRIGHT_BROWSER_TYPE?.toLowerCase() || 'chromium';
const headless = process.env.PLAYWRIGHT_HEADLESS?.toLowerCase() === 'true' || true;
const wsPath = 'playwright';
console.log('using port:', port, 'browser:', browserType, 'headless:', headless, 'wspath:', wsPath);

const serverPromise = playwright[browserType].launchServer({ headless: headless, port: port, wsPath: wsPath });
serverPromise.then(bs => console.log(bs.wsEndpoint()));
