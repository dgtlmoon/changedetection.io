FROM python:3.8-buster
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

# So that it can find the certs
WORKDIR /app

CMD [ "python", "/app/backend.py" ]

