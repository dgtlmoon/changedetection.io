#  changedetection.io
![changedetection.io](https://github.com/dgtlmoon/changedetection.io/actions/workflows/python-app.yml/badge.svg?branch=master)
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/docker/pulls/dgtlmoon/changedetection.io" alt="Docker Pulls"/>
</a>
<a href="https://hub.docker.com/r/dgtlmoon/changedetection.io" target="_blank" title="Change detection docker hub">
  <img src="https://img.shields.io/docker/v/dgtlmoon/changedetection.io" alt="Change detection latest tag version"/> 
</a>

## Self-hosted change monitoring of web pages.

_Know when web pages change! Stay ontop of new information!_


#### Example use cases

Know when ...

- Government department updates (changes are often only on their websites)
- Local government news (changes are often only on their websites)
- New software releases, security advisories when you're not on their mailing list.
- Festivals with changes
- Realestate listing changes


**Get monitoring now! super simple, one command!**

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

Application running.

![Self-hosted web page change monitoring application screenshot](screenshot.png?raw=true "Self-hosted web page change monitoring screenshot")

Examining differences in content.

![Self-hosted web page change monitoring context difference screenshot](screenshot-diff.png?raw=true "Self-hosted web page change monitoring context difference screenshot")

### Future plans

- Greater configuration of check interval times, page request headers.
- ~~General options for timeout, default headers~~
- On change detection, callout to another API (handy for notices/issue trackers)
- ~~Explore the differences that were detected~~ 
- Add more options to explore versions of differences
- Use a graphic/rendered page difference instead of text (see the experimental `selenium-screenshot-diff` branch)

 
Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/
