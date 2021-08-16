#  changedetection.io
![changedetection.io](https://github.com/dgtlmoon/changedetection.io/actions/workflows/test-only.yml/badge.svg?branch=master)
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/docker/pulls/dgtlmoon/changedetection.io" alt="Docker Pulls"/>
</a>
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/github/v/release/dgtlmoon/changedetection.io" alt="Change detection latest tag version"/> 
</a>

## Self-hosted open source change monitoring of web pages.

_Know when web pages change! Stay ontop of new information!_ 

Live your data-life *pro-actively* instead of *re-actively*, do not rely on manipulative social media for consuming important information.


<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot.png" style="max-width:100%;" alt="Self-hosted web page change monitoring"  title="Self-hosted web page change monitoring"  />

#### Example use cases

Know when ...

- Government department updates (changes are often only on their websites)
- Local government news (changes are often only on their websites)
- New software releases, security advisories when you're not on their mailing list.
- Festivals with changes
- Realestate listing changes
- COVID related news from government websites
- Detect and monitor changes in JSON API responses 
- API monitoring and alerting

**Get monitoring now!**

```bash
$ pip3 install changedetection.io   
```

Specify a target for the *datastore path* with `-d` (required) and a *listening port* with `-p` (defaults to `5000`)

```bash
$ changedetection.io -d /path/to/empty/data/dir -p 5000
```


Then visit http://127.0.0.1:5000 , You should now be able to access the UI.

### Features
- Website monitoring
- Change detection of content and analyses
- Filters on change (Select by CSS or JSON)
- Triggers (Wait for text, wait for regex)
- Notification support
- JSON API Monitoring
- Parse JSON embedded in HTML
- (Reverse) Proxy support
- Javascript support via WebDriver
- RaspberriPi (arm v6/v7/64 support)

See https://github.com/dgtlmoon/changedetection.io for more information.



### Support us

Do you use changedetection.io to make money? does it save you time or money? Does it make your life easier? less stressful? Remember, we write this software when we should be doing actual paid work, we have to buy food and pay rent just like you.

Please support us, even small amounts help a LOT.

BTC `1PLFN327GyUarpJd7nVe7Reqg9qHx5frNn`

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/btc-support.png" style="max-width:50%;" alt="Support us!"  />
