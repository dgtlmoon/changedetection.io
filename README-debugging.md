# python env
```bash
python3 -m venv ./.venv 
source ./.venv/bin/activate
```

## launch

### playwright:
launch browserless:
```bash
docker run --rm -p 3000:3000 browserless/chrome 
```

launch changedetection:
```bash
PLAYWRIGHT_DRIVER_URL="ws://localhost:3000/?stealth=1&--disable-web-security=true" python3 changedetection.py -d $(pwd)/datastore -p 5000
```

### selenium:
launch selenium:
```bash
docker run --rm -p 4444:4444 -v /dev/shm:/dev/shm selenium/standalone-chrome-debug:3.141.59
```

launch changedetection:
```bash
WEBDRIVER_URL="http://localhost:4444/wd/hub" python3 changedetection.py -d $(pwd)/datastore -p 5000
```