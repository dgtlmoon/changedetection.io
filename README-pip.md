## Web Site Change Detection, Monitoring and Notification.

Live your data-life pro-actively, track website content changes and receive notifications via Discord, Email, Slack, Telegram and 70+ more

[<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/docs/screenshot.png" style="max-width:100%;" alt="Self-hosted web page change monitoring"  title="Self-hosted web page change monitoring"  />](https://lemonade.changedetection.io/start?src=pip)


[**Don't have time? Let us host it for you! try our extremely affordable subscription use our proxies and support!**](https://lemonade.changedetection.io/start) 


#### Example use cases

- Products and services have a change in pricing
- _Out of stock notification_ and _Back In stock notification_
- Governmental department updates (changes are often only on their websites)
- New software releases, security advisories when you're not on their mailing list.
- Festivals with changes
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

_Need an actual Chrome runner with Javascript support? We support fetching via WebDriver and Playwright!</a>_

#### Key Features

- Lots of trigger filters, such as "Trigger on text", "Remove text by selector", "Ignore text", "Extract text", also using regular-expressions!
- Target elements with xPath and CSS Selectors, Easily monitor complex JSON with JsonPath rules
- Switch between fast non-JS and Chrome JS based "fetchers"
- Easily specify how often a site should be checked
- Execute JS before extracting text (Good for logging in, see examples in the UI!)
- Override Request Headers, Specify `POST` or `GET` and other methods
- Use the "Visual Selector" to help target specific elements


```bash
$ pip3 install changedetection.io
```

Specify a target for the *datastore path* with `-d` (required) and a *listening port* with `-p` (defaults to `5000`)

```bash
$ changedetection.io -d /path/to/empty/data/dir -p 5000
```


Then visit http://127.0.0.1:5000 , You should now be able to access the UI.

See https://github.com/dgtlmoon/changedetection.io for more information.

