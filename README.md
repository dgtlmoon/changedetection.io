#  changedetection.io
![changedetection.io](https://github.com/dgtlmoon/changedetection.io/actions/workflows/test-only.yml/badge.svg?branch=master)
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/docker/pulls/dgtlmoon/changedetection.io" alt="Docker Pulls"/>
</a>
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/github/v/release/dgtlmoon/changedetection.io" alt="Change detection latest tag version"/> 
</a>

## Self-hosted change monitoring of web pages.

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


**Get monitoring now! super simple, one command!**
Run the python code on your own machine by cloning this repository, or with <a href="https://docs.docker.com/get-docker/">docker</a> and/or <a href="https://www.digitalocean.com/community/tutorial_collections/how-to-install-docker-compose">docker-compose</a>

With one docker-compose command

```bash
docker-compose up -d
```

or


```bash
docker run -d --restart always -p "127.0.0.1:5000:5000" -v datastore-volume:/datastore --name changedetection.io dgtlmoon/changedetection.io
```  

Now visit http://127.0.0.1:5000 , You should now be able to access the UI.

#### Updating to latest version

Highly recommended :)

```bash
docker pull dgtlmoon/changedetection.io
docker kill $(docker ps -a|grep changedetection.io|awk '{print $1}')
docker rm $(docker ps -a|grep changedetection.io|awk '{print $1}')
docker run -d --restart always -p "127.0.0.1:5000:5000" -v datastore-volume:/datastore --name changedetection.io dgtlmoon/changedetection.io
```
  
### Screenshots

Examining differences in content.


<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot-diff.png" style="max-width:100%;" alt="Self-hosted web page change monitoring context difference "  title="Self-hosted web page change monitoring context difference " />

Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/

### Notifications

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
 
<a href="https://github.com/caronc/apprise">And everything else in this list!</a>

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/screenshot-notifications.png" style="max-width:100%;" alt="Self-hosted web page change monitoring notifications"  title="Self-hosted web page change monitoring notifications"  />

### Proxy

A proxy for ChangeDectection.io can be configured by setting environment the 
`HTTP_PROXY`, `HTTPS_PROXY` variables, examples are also in the `docker-compose.yml`

`NO_PROXY` exclude list can be specified by following `"localhost,192.168.0.0/24"`

as `docker run` with `-e`

```
docker run -d --restart always -e HTTPS_PROXY="socks5h://10.10.1.10:1080" -p "127.0.0.1:5000:5000" -v datastore-volume:/datastore --name changedetection.io dgtlmoon/changedetection.io
```

With `docker-compose`, see the `Proxy support example` in <a href="https://github.com/dgtlmoon/changedetection.io/blob/master/docker-compose.yml">docker-compose.yml</a>.

For more information see https://docs.python-requests.org/en/master/user/advanced/#proxies

This proxy support also extends to the notifications https://github.com/caronc/apprise/issues/387#issuecomment-841718867

### Notes

- Does not yet support Javascript
- Wont work with Cloudfare type "Please turn on javascript" protected pages
- You can use the 'headers' section to monitor password protected web page changes

### RaspberriPi support?

RaspberriPi and linux/arm/v6 linux/arm/v7 arm64 devices are supported! 


### Support us

Do you use changedetection.io to make money? does it save you time or money? Does it make your life easier? less stressful? Remember, we write this software when we should be doing actual paid work, we have to buy food and pay rent just like you.

Please support us, even small amounts help a LOT.

BTC `1PLFN327GyUarpJd7nVe7Reqg9qHx5frNn`

<img src="https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/btc-support.png" style="max-width:50%;" alt="Support us!"  />
