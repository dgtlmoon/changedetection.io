FROM python:3.8-slim

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN [ ! -d "/datastore" ] && mkdir /datastore

COPY sleep.py /
CMD [ "python", "/sleep.py" ]



