# Real-time Socket.IO Implementation

This directory contains the Socket.IO implementation for changedetection.io's real-time updates.

## Architecture Overview

The real-time system provides live updates to the web interface for:
- Watch status changes (checking, completed, errors)
- Queue length updates  
- General statistics updates

## Current Implementation

### Socket.IO Configuration
- **Async Mode**: `threading` (default) or `gevent` (optional via SOCKETIO_MODE env var)
- **Server**: Flask-SocketIO with threading support
- **Background Tasks**: Python threading with daemon threads

### Async Worker Integration
- **Workers**: Async workers using asyncio for watch processing
- **Queue**: AsyncSignalPriorityQueue for job distribution
- **Signals**: Blinker signals for real-time updates between workers and Socket.IO

### Environment Variables
- `SOCKETIO_MODE=threading` (default, recommended)
- `SOCKETIO_MODE=gevent` (optional, has cross-platform limitations)

## Architecture Decision: Why Threading Mode?

### Previous Issues with Eventlet
**Eventlet was completely removed** due to fundamental compatibility issues:

1. **Monkey Patching Conflicts**: `eventlet.monkey_patch()` globally replaced Python's threading/socket modules, causing conflicts with:
   - Playwright's synchronous browser automation
   - Async worker event loops
   - Various Python libraries expecting real threading

2. **Python 3.12+ Compatibility**: Eventlet had issues with newer Python versions and asyncio integration

3. **CVE-2023-29483**: Security vulnerability in eventlet's dnspython dependency

### Current Solution Benefits
✅ **Threading Mode Advantages**:
- Full compatibility with async workers and Playwright
- No monkey patching - uses standard Python threading
- Better Python 3.12+ support
- Cross-platform compatibility (Windows, macOS, Linux)
- No external async library dependencies
- Fast shutdown capabilities

✅ **Optional Gevent Support**:
- Available via `SOCKETIO_MODE=gevent` for high-concurrency scenarios
- Cross-platform limitations documented in requirements.txt
- Not recommended as default due to Windows socket limits and macOS ARM build issues

## Socket.IO Mode Configuration

### Threading Mode (Default)
```python
# Enabled automatically
async_mode = 'threading'
socketio = SocketIO(app, async_mode='threading')
```

### Gevent Mode (Optional)
```bash
# Set environment variable
export SOCKETIO_MODE=gevent
```

## Background Tasks

### Queue Polling
- **Threading Mode**: `threading.Thread` with `threading.Event` for shutdown
- **Signal Handling**: Blinker signals for watch state changes
- **Real-time Updates**: Direct Socket.IO `emit()` calls to connected clients

### Worker Integration
- **Async Workers**: Run in separate asyncio event loop thread
- **Communication**: AsyncSignalPriorityQueue bridges async workers and Socket.IO
- **Updates**: Real-time updates sent when workers complete tasks

## Files in This Directory

- `socket_server.py`: Main Socket.IO initialization and event handling
- `events.py`: Watch operation event handlers  
- `__init__.py`: Module initialization

## Production Deployment

### Recommended WSGI Servers
For production with Socket.IO threading mode:
- **Gunicorn**: `gunicorn --worker-class eventlet changedetection:app` (if using gevent mode)
- **uWSGI**: With threading support
- **Docker**: Built-in Flask server works well for containerized deployments

### Performance Considerations
- Threading mode: Better memory usage, standard Python threading
- Gevent mode: Higher concurrency but platform limitations
- Async workers: Separate from Socket.IO, provides scalability

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SOCKETIO_MODE` | `threading` | Socket.IO async mode (`threading` or `gevent`) |
| `FETCH_WORKERS` | `10` | Number of async workers for watch processing |
| `CHANGEDETECTION_HOST` | `0.0.0.0` | Server bind address |
| `CHANGEDETECTION_PORT` | `5000` | Server port |

## Debugging Tips

1. **Socket.IO Issues**: Check browser dev tools for WebSocket connection errors
2. **Threading Issues**: Monitor with `ps -T` to check thread count  
3. **Worker Issues**: Use `/worker-health` endpoint to check async worker status
4. **Queue Issues**: Use `/queue-status` endpoint to monitor job queue
5. **Performance**: Use `/gc-cleanup` endpoint to trigger memory cleanup

## Migration Notes

If upgrading from eventlet-based versions:
- Remove any `EVENTLET_*` environment variables
- No code changes needed - Socket.IO mode is automatically configured
- Optional: Set `SOCKETIO_MODE=gevent` if high concurrency is required and platform supports it