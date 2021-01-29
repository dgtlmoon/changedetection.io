#  changedetection.io

## Self-hosted change monitoring of web pages.

_Why?_ Many years ago I had used a couple of web site change detection/monitoring services, 
but they got bought up by larger media companies, after this, whenI logged in they
wanted _even more_ private data about me.

All I simply wanted todo was to know which pages were changing and when (and maybe see
some basic information about what those changes were)

![Alt text](screenshot.png?raw=true "Screenshot")

Get monitoring! super simple.

```
$ mkdir ./datastore
$ docker run -d --restart always -p "127.0.0.1:5000:5000" -v "$(pwd)"/datastore:/datastore dgtlmoon/changedetection.io
```  

Now visit http://127.0.0.1:5000 , The interface will now expose the UI, you can change this in the `docker-compose.yml`



Or in `docker-compose.yml` style.


```yaml
version: "2"
services:

  backend:
    image: dgtlmoon/changedetection.io:latest
    volumes:
      - ./datastore:/datastore
    ports:
      - "127.0.0.1:5000:5000"
    restart: always
```

```bash
$ mkdir datastore
$ docker-compose up -d
```


### Future plans

- Greater configuration of check interval times, page request headers.
- General options for timeout, default headers
- On change detection, callout to another API (handy for notices/issue trackers)
- Explore the differences that were detected.
- Use a graphic/rendered page difference instead of text (see the experimental `selenium-screenshot-diff` branch)

 
Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/