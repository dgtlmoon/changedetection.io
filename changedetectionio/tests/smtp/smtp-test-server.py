#!/usr/bin/python3
import smtpd
import asyncore

# Accept a SMTP message and offer a way to retrieve the last message via TCP Socket

last_received_message = b"Nothing"


class CustomSMTPServer(smtpd.SMTPServer):

    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        global last_received_message
        last_received_message = data
        print('Receiving message from:', peer)
        print('Message addressed from:', mailfrom)
        print('Message addressed to  :', rcpttos)
        print('Message length        :', len(data))
        print(data.decode('utf8'))
        return


# Just print out the last message received on plain TCP socket server
class EchoServer(asyncore.dispatcher):

    def __init__(self, host, port):
        asyncore.dispatcher.__init__(self)
        self.create_socket()
        self.set_reuse_addr()
        self.bind((host, port))
        self.listen(5)

    def handle_accepted(self, sock, addr):
        global last_received_message
        print('Incoming connection from %s' % repr(addr))
        sock.send(last_received_message)
        last_received_message = b''


server = CustomSMTPServer(('0.0.0.0', 11025), None)  # SMTP mail goes here
server2 = EchoServer('0.0.0.0', 11080)  # Echo back last message received
asyncore.loop()
