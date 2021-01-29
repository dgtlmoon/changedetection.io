#  changedetection.io

## Self-hosted change monitoring of web pages.

_Know when web pages change! Stay ontop of new information!_


#### Use cases

Know when ...

- Government department updates (changes are often only on their websites)
- Local government news (changes are often only on their websites)
- New software releases 
- Festivals with changes
- Realestate listing changes


  

![Alt text](screenshot.png?raw=true "Screenshot")

Get monitoring! super simple.

```
$ mkdir ./datastore
$ docker run -d --restart always -p "127.0.0.1:5000:5000" -v "$(pwd)"/datastore:/datastore dgtlmoon/changedetection.io
```  

Now visit http://127.0.0.1:5000 , You should now be able to access the UI.



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
(`/datastore` is optional, I prefer to have the files on my local disk instead of in a docker volume)

### Future plans

- Greater configuration of check interval times, page request headers.
- General options for timeout, default headers
- On change detection, callout to another API (handy for notices/issue trackers)
- Explore the differences that were detected.
- Use a graphic/rendered page difference instead of text (see the experimental `selenium-screenshot-diff` branch)

 
Please :star: star :star: this project and help it grow! https://github.com/dgtlmoon/changedetection.io/