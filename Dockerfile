FROM python:3.8-slim

# rustc compiler would be needed on ARM type devices but theres an issue with some deps not building..
ARG CRYPTOGRAPHY_DONT_BUILD_RUST=1

COPY requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y libssl-dev libffi-dev gcc libc-dev libxslt-dev zlib1g-dev rustc g++ --no-install-recommends && rm -rf /var/lib/apt/lists/* /var/cache/apt/*
RUN pip3 install --upgrade pip && pip3 install --no-cache-dir -r /tmp/requirements.txt 

 
RUN [ ! -d "/app" ] && mkdir /app
RUN [ ! -d "/datastore" ] && mkdir /datastore

# The actual flask app
COPY backend /app/backend

# The eventlet server wrapper
COPY changedetection.py /app/changedetection.py

WORKDIR /app

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

# Attempt to store the triggered commit
ARG SOURCE_COMMIT
ARG SOURCE_BRANCH
RUN apt-get remove rustc *-dev --purge -y
RUN echo "commit: $SOURCE_COMMIT branch: $SOURCE_BRANCH" >/source.txt

CMD [ "python", "./changedetection.py" , "-d", "/datastore"]



