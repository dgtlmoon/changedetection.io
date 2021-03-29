FROM python:3.8-slim
COPY requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y gcc libc-dev libxslt-dev zlib1g-dev g++

RUN pip3 install -r /tmp/requirements.txt


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
RUN echo "commit: $SOURCE_COMMIT branch: $SOURCE_BRANCH" >/source.txt

CMD [ "python", "./changedetection.py" , "-d", "/datastore"]



