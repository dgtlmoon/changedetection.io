FROM python:3.8-slim

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

# Should be mounted from docker-compose-development.yml
RUN pip3 install -r /requirements.txt


RUN [ ! -d "/datastore" ] && mkdir /datastore

COPY sleep.py /
CMD [ "python", "/sleep.py" ]



