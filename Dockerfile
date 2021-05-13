FROM python:3.8-slim
COPY requirements.txt /tmp/requirements.txt
RUN apt-get update && apt-get install -y libssl-dev libffi-dev gcc libc-dev libxslt-dev zlib1g-dev g++ --no-install-recommends && rm -rf /var/lib/apt/lists/* /var/cache/apt/*
RUN pip3 install --upgrade pip && pip3 install --no-cache-dir -r /tmp/requirements.txt

 
# More bloat, curl above is needed because the rust compiler is needed
# apprise requires this cryptography lib
#RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y


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



