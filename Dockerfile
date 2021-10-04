# pip dependencies install stage
#FROM python:3.8-slim as builder

FROM python:3.8.12-alpine3.14 as builder
RUN apk update && apk add --update build-base bash linux-headers build-base python3-dev py-pip libwebp-dev jpeg-dev zlib-dev postgresql-dev libffi-dev rust gcc musl-dev openssl-dev cargo libxml2-dev libxslt-dev

# rustc compiler would be needed on ARM type devices but theres an issue with some deps not building..
ARG CRYPTOGRAPHY_DONT_BUILD_RUST=1

#RUN apt-get update && apt-get install -y --no-install-recommends \
#    libssl-dev \
#    libffi-dev \
#    gcc \
#    libc-dev \
#    libxslt-dev \
#    zlib1g-dev \
#    g++

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /requirements.txt

RUN pip install --target=/dependencies -r /requirements.txt

# Final image stage
FROM python:3.8.12-alpine3.14

# Actual packages needed at runtime, usually due to the notification (apprise) backend
# rustc compiler would be needed on ARM type devices but theres an issue with some deps not building..
ARG CRYPTOGRAPHY_DONT_BUILD_RUST=1

# Re #93, #73, excluding rustc (adds another 430Mb~)
RUN apk update && apk add --update \
    libffi-dev \
    gcc \
    libc-dev \
    libxslt-dev \
    g++

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

RUN [ ! -d "/datastore" ] && mkdir /datastore

# Copy modules over to the final image and add their dir to PYTHONPATH
COPY --from=builder /dependencies /usr/local
ENV PYTHONPATH=/usr/local

# The actual flask app
COPY changedetectionio /app/changedetectionio
# The eventlet server wrapper
COPY changedetection.py /app/changedetection.py

WORKDIR /app

CMD [ "python", "./changedetection.py" , "-d", "/datastore"]
