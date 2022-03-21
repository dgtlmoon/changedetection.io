FROM mcr.microsoft.com/playwright:v1.20.0-focal

WORKDIR /server
RUN npm install playwright
COPY server.js .

ENV PLAYWRIGHT_PORT=4444
ENV PLAYWRIGHT_BROWSER_TYPE=chromium
ENV PLAYWRIGHT_HEADLESS=true

EXPOSE ${PLAYWRIGHT_PORT}

CMD [ "node", "server.js" ]
