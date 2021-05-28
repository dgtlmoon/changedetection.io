FROM python:3.8-slim

# rustc compiler would be needed on ARM type devices but theres an issue with some deps not building..
ARG CRYPTOGRAPHY_DONT_BUILD_RUST=1

COPY requirements.txt /tmp/requirements.txt

RUN apt-get update && apt-get install -y libssl-dev libffi-dev gcc libc-dev libxslt-dev zlib1g-dev rustc g++ --no-install-recommends && rm -rf /var/lib/apt/lists/* /var/cache/apt/*
# Update pip, install requirements, remove rust and dev packages that are no longer needed.
RUN pip3 install --upgrade pip && pip3 install --no-cache-dir -r /tmp/requirements.txt && apt-get remove rustc *-dev --purge -y

RUN [ ! -d "/app" ] && mkdir /app
RUN [ ! -d "/datastore" ] && mkdir /datastore

# The actual flask app
COPY backend /app/backend

# The eventlet server wrapper
COPY changedetection.py /app/changedetection.py

WORKDIR /app

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

CMD [ "python", "./changedetection.py" , "-d", "/datastore"]



