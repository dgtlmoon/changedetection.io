## Web Site Change Detection, Monitoring and Notification.

Live your data-life pro-actively, track website content changes and receive notifications via Discord, Email, Slack, Telegram and 70+ more

[<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/docs/screenshot.png" style="max-width:100%;" alt="Self-hosted web page change monitoring, list of websites with changes"  title="Self-hosted web page change monitoring, list of websites with changes"  />](https://changedetection.io)


[**Don't have time? Let us host it for you! try our extremely affordable subscription use our proxies and support!**](https://changedetection.io) 


### Target specific parts of the webpage using the Visual Selector tool.

Available when connected to a <a href="https://github.com/dgtlmoon/changedetection.io/wiki/Playwright-content-fetcher">playwright content fetcher</a> (included as part of our subscription service)

[<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/docs/visualselector-anim.gif" style="max-width:100%;" alt="Select parts and elements of a web page to monitor for changes"  title="Select parts and elements of a web page to monitor for changes" />](https://changedetection.io?src=pip)

### Easily see what changed, examine by word, line, or individual character.

[<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/docs/screenshot-diff.png" style="max-width:100%;" alt="Self-hosted web page change monitoring context difference "  title="Self-hosted web page change monitoring context difference " />](https://changedetection.io?src=pip)


### Perform interactive browser steps

Fill in text boxes, click buttons and more, setup your changedetection scenario. 

Using the **Browser Steps** configuration, add basic steps before performing change detection, such as logging into websites, adding a product to a cart, accept cookie logins, entering dates and refining searches.

[<img src="docs/browsersteps-anim.gif" style="max-width:100%;" alt="Website change detection with interactive browser steps, detect changes behind login and password, search queries and more"  title="Website change detection with interactive browser steps, detect changes behind login and password, search queries and more" />](https://changedetection.io?src=pip)

After **Browser Steps** have been run, then visit the **Visual Selector** tab to refine the content you're interested in.
Requires Playwright to be enabled.


### Example use cases

- Products and services have a change in pricing
- _Out of stock notification_ and _Back In stock notification_
- Monitor and track PDF file changes, know when a PDF file has text changes.
- Governmental department updates (changes are often only on their websites)
- New software releases, security advisories when you're not on their mailing list.
- Festivals with changes
- Discogs restock alerts and monitoring
- Realestate listing changes
- Know when your favourite whiskey is on sale, or other special deals are announced before anyone else
- COVID related news from government websites
- University/organisation news from their website
- Detect and monitor changes in JSON API responses 
- JSON API monitoring and alerting
- Changes in legal and other documents
- Trigger API calls via notifications when text appears on a website
- Glue together APIs using the JSON filter and JSON notifications
- Create RSS feeds based on changes in web content
- Monitor HTML source code for unexpected changes, strengthen your PCI compliance
- You have a very sensitive list of URLs to watch and you do _not_ want to use the paid alternatives. (Remember, _you_ are the product)
- Get notified when certain keywords appear in Twitter search results
- Proactively search for jobs, get notified when companies update their careers page, search job portals for keywords.
- Get alerts when new job positions are open on Bamboo HR and other job platforms
- Website defacement monitoring
- Pokémon Card Restock Tracker / Pokémon TCG Tracker
- RegTech - stay ahead of regulatory changes, regulatory compliance

_Need an actual Chrome runner with Javascript support? We support fetching via WebDriver and Playwright!</a>_

#### Key Features

- Lots of trigger filters, such as "Trigger on text", "Remove text by selector", "Ignore text", "Extract text", also using regular-expressions!
- Target elements with xPath(1.0) and CSS Selectors, Easily monitor complex JSON with JSONPath or jq
- Switch between fast non-JS and Chrome JS based "fetchers"
- Track changes in PDF files (Monitor text changed in the PDF, Also monitor PDF filesize and checksums)
- Easily specify how often a site should be checked
- Execute JS before extracting text (Good for logging in, see examples in the UI!)
- Override Request Headers, Specify `POST` or `GET` and other methods
- Use the "Visual Selector" to help target specific elements
- Configurable [proxy per watch](https://github.com/dgtlmoon/changedetection.io/wiki/Proxy-configuration)
- Send a screenshot with the notification when a change is detected in the web page

We [recommend and use Bright Data](https://brightdata.grsm.io/n0r16zf7eivq) global proxy services, Bright Data will match any first deposit up to $100 using our signup link.

[Oxylabs](https://oxylabs.go2cloud.org/SH2d) is also an excellent proxy provider and well worth using, they offer Residental, ISP, Rotating and many other proxy types to suit your project. 

Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/



```bash
$ pip3 install changedetection.io
```

Specify a target for the *datastore path* with `-d` (required) and a *listening port* with `-p` (defaults to `5000`)

```bash
$ changedetection.io -d /path/to/empty/data/dir -p 5000
```


Then visit http://127.0.0.1:5000 , You should now be able to access the UI.

See https://changedetection.io for more information.

