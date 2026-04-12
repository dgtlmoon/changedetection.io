#!/usr/bin/env python3
import threading
import time
from aiosmtpd.controller import Controller
from flask import Flask, Response
from email import message_from_bytes
from email.policy import default

# Accept a SMTP message and offer a way to retrieve the last message via HTTP

last_received_message = b"SMTP Test Server - Nothing received yet."
active_smtp_connections = 0
smtp_lock = threading.Lock()


class CustomSMTPHandler:
    async def handle_DATA(self, server, session, envelope):
        global last_received_message, active_smtp_connections

        with smtp_lock:
            active_smtp_connections += 1

        try:
            last_received_message = envelope.content
            print('Receiving message from:', session.peer)
            print('Message addressed from:', envelope.mail_from)
            print('Message addressed to  :', envelope.rcpt_tos)
            print('Message length        :', len(envelope.content))
            print('*******************************')
            print(envelope.content.decode('utf8'))
            print('*******************************')

            # Parse the email message
            msg = message_from_bytes(envelope.content, policy=default)
            with open('/tmp/last.eml', 'wb') as f:
                f.write(envelope.content)

            # Write parts to files based on content type
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    payload = part.get_payload(decode=True)

                    if payload:
                        if content_type == 'text/plain':
                            with open('/tmp/last.txt', 'wb') as f:
                                f.write(payload)
                            print(f'Written text/plain part to /tmp/last.txt')
                        elif content_type == 'text/html':
                            with open('/tmp/last.html', 'wb') as f:
                                f.write(payload)
                            print(f'Written text/html part to /tmp/last.html')
            else:
                # Single part message
                content_type = msg.get_content_type()
                payload = msg.get_payload(decode=True)

                if payload:
                    if content_type == 'text/plain' or content_type.startswith('text/'):
                        with open('/tmp/last.txt', 'wb') as f:
                            f.write(payload)
                        print(f'Written single part message to /tmp/last.txt')

            return '250 Message accepted for delivery'
        finally:
            with smtp_lock:
                active_smtp_connections -= 1


# Simple Flask HTTP server to echo back the last SMTP message
app = Flask(__name__)


@app.route('/')
def echo_last_message():
    global last_received_message, active_smtp_connections

    # Wait for any in-progress SMTP connections to complete
    max_wait = 5  # Maximum 5 seconds
    wait_interval = 0.05  # Check every 50ms
    elapsed = 0

    while elapsed < max_wait:
        with smtp_lock:
            if active_smtp_connections == 0:
                break
        time.sleep(wait_interval)
        elapsed += wait_interval

    return Response(last_received_message, mimetype='text/plain')


def run_flask():
    app.run(host='0.0.0.0', port=11080, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Start the SMTP server
    controller = Controller(CustomSMTPHandler(), hostname='0.0.0.0', port=11025)
    controller.start()

    # Start the HTTP server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Keep the main thread alive
    try:
        flask_thread.join()
    except KeyboardInterrupt:
        print("Shutting down...")
