import asyncio
import socketio

# URL of your Socket.IO server
SOCKETIO_URL = "http://localhost:5000"  # Change as needed
SOCKETIO_PATH = "/socket.io"  # Match the path used in your JS config

# Number of clients to simulate
NUM_CLIENTS = 10

async def start_client(client_id: int):
    sio = socketio.AsyncClient(reconnection_attempts=5, reconnection_delay=1)

    @sio.event
    async def connect():
        print(f"[Client {client_id}] Connected")

    @sio.event
    async def disconnect():
        print(f"[Client {client_id}] Disconnected")

    @sio.on("watch_update")
    async def on_watch_update(watch):
        print(f"[Client {client_id}] Received update: {watch}")

    try:
        await sio.connect(SOCKETIO_URL, socketio_path=SOCKETIO_PATH, transports=["websocket", "polling"])
        await sio.wait()
    except Exception as e:
        print(f"[Client {client_id}] Connection error: {e}")

async def main():
    clients = [start_client(i) for i in range(NUM_CLIENTS)]
    await asyncio.gather(*clients)

if __name__ == "__main__":
    asyncio.run(main())
