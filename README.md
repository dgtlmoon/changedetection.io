#  changedetection.io
[![Release Version][release-shield]][release-link] [![Docker Pulls][docker-pulls]][docker-link] [![License][license-shield]](LICENSE.md)

![changedetection.io](https://github.com/dgtlmoon/changedetection.io/actions/workflows/test-only.yml/badge.svg?branch=master)

## Self-Hosted, Open Source, Change Monitoring of Web Pages

_Know when web pages change! Stay ontop of new information!_ 

Live your data-life *pro-actively* instead of *re-actively*.

Free, Open-source web page monitoring, notification and change detection. Don't have time? [**Try our $6.99/month subscription - unlimited checks and watches!**](https://lemonade.changedetection.io/start)


[<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot.png" style="max-width:100%;" alt="Self-hosted web page change monitoring"  title="Self-hosted web page change monitoring"  />](https://lemonade.changedetection.io/start)


**Get your own private instance now! Let us host it for you!**

[**Try our $6.99/month subscription - unlimited checks and watches!**](https://lemonade.changedetection.io/start) , _half the price of other website change monitoring services and comes with unlimited watches & checks!_



- Automatic Updates, Automatic Backups, No Heroku "paused application", don't miss a change!
- Javascript browser included
- Unlimited checks and watches!


#### Example use cases

- Products and services have a change in pricing
- Governmental department updates (changes are often only on their websites)
- New software releases, security advisories when you're not on their mailing list.
- Festivals with changes
- Realestate listing changes
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

_Need an actual Chrome runner with Javascript support? We support fetching via WebDriver!</a>_

## Screenshots

Examining differences in content.

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot-diff.png" style="max-width:100%;" alt="Self-hosted web page change monitoring context difference "  title="Self-hosted web page change monitoring context difference " />

Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/


## Installation

### Docker

With Docker composer, just clone this repository and..
```bash
$ docker-compose up -d
```
Docker standalone
```bash
$ docker run -d --restart always -p "127.0.0.1:5000:5000" -v datastore-volume:/datastore --name changedetection.io dgtlmoon/changedetection.io
```

### Windows

See the install instructions at the wiki https://github.com/dgtlmoon/changedetection.io/wiki/Microsoft-Windows

### Python Pip

Check out our pypi page https://pypi.org/project/changedetection.io/

```bash
$ pip3 install changedetection.io
$ changedetection.io -d /path/to/empty/data/dir -p 5000
```

Then visit http://127.0.0.1:5000 , You should now be able to access the UI.

_Now with per-site configurable support for using a fast built in HTTP fetcher or use a Chrome based fetcher for monitoring of JavaScript websites!_

## Updating changedetection.io

### Docker
```
docker pull dgtlmoon/changedetection.io
docker kill $(docker ps -a|grep changedetection.io|awk '{print $1}')
docker rm $(docker ps -a|grep changedetection.io|awk '{print $1}')
docker run -d --restart always -p "127.0.0.1:5000:5000" -v datastore-volume:/datastore --name changedetection.io dgtlmoon/changedetection.io
```

### docker-compose

```bash
docker-compose pull && docker-compose up -d
```

See the wiki for more information https://github.com/dgtlmoon/changedetection.io/wiki


## Filters
XPath, JSONPath and CSS support comes baked in! You can be as specific as you need, use XPath exported from various XPath element query creation tools.

(We support LXML re:test, re:math and re:replace.)

## Notifications

ChangeDetection.io supports a massive amount of notifications (including email, office365, custom APIs, etc) when a web-page has a change detected thanks to the <a href="https://github.com/caronc/apprise">apprise</a> library.
Simply set one or more notification URL's in the _[edit]_ tab of that watch.

Just some examples

    discord://webhook_id/webhook_token
    flock://app_token/g:channel_id
    gitter://token/room
    gchat://workspace/key/token
    msteams://TokenA/TokenB/TokenC/
    o365://TenantID:AccountEmail/ClientID/ClientSecret/TargetEmail
    rocket://user:password@hostname/#Channel
    mailto://user:pass@example.com?to=receivingAddress@example.com
    json://someserver.com/custom-api
    syslog://
 
<a href="https://github.com/caronc/apprise#popular-notification-services">And everything else in this list!</a>

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot-notifications.png" style="max-width:100%;" alt="Self-hosted web page change monitoring notifications"  title="Self-hosted web page change monitoring notifications"  />

Now you can also customise your notification content!

## JSON API Monitoring

Detect changes and monitor data in JSON API's by using the built-in JSONPath selectors as a filter / selector.

![image](https://user-images.githubusercontent.com/275001/125165842-0ce01980-e1dc-11eb-9e73-d8137dd162dc.png)

This will re-parse the JSON and apply formatting to the text, making it super easy to monitor and detect changes in JSON API results

![image](https://user-images.githubusercontent.com/275001/125165995-d9ea5580-e1dc-11eb-8030-f0deced2661a.png)

### Parse JSON embedded in HTML!

When you enable a `json:` filter, you can even automatically extract and parse embedded JSON inside a HTML page! Amazingly handy for sites that build content based on JSON, such as many e-commerce websites. 

```
<html>
...
<script type="application/ld+json">
  {"@context":"http://schema.org","@type":"Product","name":"Nan Optipro Stage 1 Baby Formula  800g","price": 23.50 }
</script>
```  

`json:$.price` would give `23.50`, or you can extract the whole structure

## Proxy configuration

See the wiki https://github.com/dgtlmoon/changedetection.io/wiki/Proxy-configuration

## Raspberry Pi support?

Raspberry Pi and linux/arm/v6 linux/arm/v7 arm64 devices are supported! See the wiki for [details](https://github.com/dgtlmoon/changedetection.io/wiki/Fetching-pages-with-WebDriver)


## Support us

Do you use changedetection.io to make money? does it save you time or money? Does it make your life easier? less stressful? Remember, we write this software when we should be doing actual paid work, we have to buy food and pay rent just like you.


Firstly, consider taking out a [change detection monthly subscription - unlimited checks and watches](https://lemonade.changedetection.io/start) , even if you don't use it, you still get the warm fuzzy feeling of helping out the project. (And who knows, you might just use it!)

Or directly donate an amount PayPal [![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/donate/?hosted_button_id=7CP6HR9ZCNDYJ)

Or BTC `1PLFN327GyUarpJd7nVe7Reqg9qHx5frNn`

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/btc-support.png" style="max-width:50%;" alt="Support us!"  />

## Commercial Support

I offer commercial support, this software is depended on by network security, aerospace , data-science and data-journalist professionals just to name a few, please reach out at dgtlmoon@gmail.com for any enquiries, I am more than glad to work with your organisation to further the possibilities of what can be done with changedetection.io


[release-shield]: https://img.shields.io:/github/v/release/dgtlmoon/changedetection.io?style=for-the-badge
[docker-pulls]: https://img.shields.io/docker/pulls/dgtlmoon/changedetection.io?style=for-the-badge
[test-shield]: https://github.com/dgtlmoon/changedetection.io/actions/workflows/test-only.yml/badge.svg?branch=master

[license-shield]: https://img.shields.io/github/license/dgtlmoon/changedetection.io.svg?style=for-the-badge
[release-link]: https://github.com/dgtlmoon.com/changedetection.io/releases
[docker-link]: https://hub.docker.com/r/dgtlmoon/changedetection.io
