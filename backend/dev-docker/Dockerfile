FROM python:3.8-slim

# https://stackoverflow.com/questions/58701233/docker-logs-erroneously-appears-empty-until-container-stops
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt


RUN [ ! -d "/datastore" ] && mkdir /datastore

COPY sleep.py /
CMD [ "python", "/sleep.py" ]



