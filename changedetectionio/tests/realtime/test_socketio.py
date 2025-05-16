import asyncio
import socketio
from aiohttp import web

SOCKETIO_URL = 'ws://localhost.localdomain:5005'
SOCKETIO_PATH = "/socket.io"
NUM_CLIENTS = 1

clients = []
shutdown_event = asyncio.Event()

class WatchClient:
    def __init__(self, client_id: int):
        self.client_id = client_id
        self.i_got_watch_update_event = False
        self.sio = socketio.AsyncClient(reconnection_attempts=50, reconnection_delay=1)

        @self.sio.event
        async def connect():
            print(f"[Client {self.client_id}] Connected")

        @self.sio.event
        async def disconnect():
            print(f"[Client {self.client_id}] Disconnected")

        @self.sio.on("watch_update")
        async def on_watch_update(watch):
            self.i_got_watch_update_event = True
            print(f"[Client {self.client_id}] Received update: {watch}")

    async def run(self):
        try:
            await self.sio.connect(SOCKETIO_URL, socketio_path=SOCKETIO_PATH, transports=["websocket", "polling"])
            await self.sio.wait()
        except Exception as e:
            print(f"[Client {self.client_id}] Connection error: {e}")

async def handle_check(request):
    all_received = all(c.i_got_watch_update_event for c in clients)
    result = "yes" if all_received else "no"
    print(f"Received HTTP check — returning '{result}'")
    shutdown_event.set()  # Signal shutdown
    return web.Response(text=result)

async def start_http_server():
    app = web.Application()
    app.add_routes([web.get('/did_all_clients_get_watch_update', handle_check)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 6666)
    await site.start()

async def main():
    #await start_http_server()

    for i in range(NUM_CLIENTS):
        client = WatchClient(i)
        clients.append(client)
        asyncio.create_task(client.run())

    await shutdown_event.wait()

    print("Shutting down...")
    # Graceful disconnect
    for c in clients:
        await c.sio.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
