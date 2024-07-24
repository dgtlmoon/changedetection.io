#!/usr/bin/env python3
import asyncio
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP

# Accept a SMTP message and offer a way to retrieve the last message via TCP Socket

last_received_message = b"Nothing"


class CustomSMTPHandler:
    async def handle_DATA(self, server, session, envelope):
        global last_received_message
        last_received_message = envelope.content
        print('Receiving message from:', session.peer)
        print('Message addressed from:', envelope.mail_from)
        print('Message addressed to  :', envelope.rcpt_tos)
        print('Message length        :', len(envelope.content))
        print(envelope.content.decode('utf8'))
        return '250 Message accepted for delivery'


class EchoServerProtocol(asyncio.Protocol):
    def connection_made(self, transport):
        global last_received_message
        self.transport = transport
        peername = transport.get_extra_info('peername')
        print('Incoming connection from {}'.format(peername))
        self.transport.write(last_received_message)

        last_received_message = b''
        self.transport.close()


async def main():
    # Start the SMTP server
    controller = Controller(CustomSMTPHandler(), hostname='0.0.0.0', port=11025)
    controller.start()

    # Start the TCP Echo server
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: EchoServerProtocol(),
        '0.0.0.0', 11080
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
