# Real-time Socket.IO Implementation

This directory contains the Socket.IO implementation for changedetection.io's real-time updates.

## Architecture Overview

The real-time system provides live updates to the web interface for:
- Watch status changes (checking, completed, errors)
- Queue length updates
- General statistics updates

## Historical Issues and Solutions

### Eventlet vs Playwright Conflicts

**Problem**: The application originally used `eventlet.monkey_patch()` to enable green threading for Socket.IO, but this caused severe conflicts with Playwright's synchronous browser automation.

#### Symptoms:
1. **Playwright hanging**: The `with sync_playwright() as p:` context manager would hang when exiting, preventing proper cleanup
2. **Greenlet thread switching errors**: 
   ```
   greenlet.error: Cannot switch to a different thread
   Current:  <greenlet.greenlet object at 0x...> 
   Expected: <greenlet.greenlet object at 0x...>
   ```

#### Root Cause:
- `eventlet.monkey_patch()` globally patches Python's threading, socket, and I/O modules
- Playwright's sync API relies on real OS threads for browser communication and cleanup
- When eventlet patches threading, it replaces real threads with green threads (greenlets)
- Playwright's internal operations try to switch between real threads, but eventlet expects greenlet switching
- This creates an incompatible execution model

### Solution Evolution

#### Attempt 1: Selective Monkey Patching
```python
# Tried to patch only specific modules
eventlet.monkey_patch(socket=True, select=True, time=True, thread=False, os=False)
```
**Result**: Still had conflicts because Socket.IO operations interacted with Playwright's threaded operations.

#### Attempt 2: Complete Eventlet Removal
**Final Solution**: Removed eventlet monkey patching entirely and switched to threading-based Socket.IO:

```python
# Before
async_mode = 'eventlet'
eventlet.monkey_patch()
polling_thread = eventlet.spawn(polling_function)

# After  
async_mode = 'threading'
# No monkey patching
polling_thread = threading.Thread(target=polling_function, daemon=True)
```

## Current Implementation

### Socket.IO Configuration
- **Async Mode**: `eventlet` (restored)
- **Server**: Eventlet WSGI server
- **Threading**: Eventlet greenlets for background tasks

### Playwright Integration
- **API**: `async_playwright()` instead of `sync_playwright()`
- **Execution**: Runs in separate asyncio event loops when called from Flask routes
- **Browser Steps**: Fully converted to async operations

### Background Tasks
- **Queue polling**: Uses eventlet greenlets with `eventlet.Event` for clean shutdown
- **Signal handling**: Blinker signals for watch updates
- **Real-time updates**: Direct Socket.IO `emit()` calls to connected clients

### Trade-offs

#### Benefits:
- ✅ No conflicts between eventlet and Playwright (async mode)
- ✅ No greenlet thread switching errors  
- ✅ Full SocketIO functionality restored
- ✅ Better performance with eventlet green threads
- ✅ Production-ready eventlet server

#### Implementation Details:
- ✅ Async Playwright runs in isolated asyncio event loops
- ✅ Flask routes use `asyncio.run_until_complete()` for async calls
- ✅ Browser steps session management fully async

## Alternative Approaches Considered

### 1. Async Playwright
Converting to `async_playwright()` would eliminate sync context conflicts, but:
- Major refactoring required across the entire content fetcher system
- Async/await propagation through the codebase
- Potential compatibility issues with other sync operations

### 2. Process Isolation  
Running Playwright in separate processes via multiprocessing:
- Added complexity for IPC
- Overhead of process creation/communication
- Difficult error handling and resource management

### 3. Eventlet Import Patching
Using `eventlet.import_patched()` for specific modules:
- Still had underlying thread model conflicts
- Selective patching complexity
- Maintenance burden

## Best Practices

### When Adding New Features:
1. **Avoid** `eventlet.monkey_patch()` calls
2. **Use** standard Python threading for background tasks
3. **Test** Socket.IO functionality with concurrent Playwright operations
4. **Monitor** for thread safety issues in shared resources

### For Production Deployment:
Consider replacing Werkzeug with a production WSGI server that supports Socket.IO threading mode, such as:
- Gunicorn with threading workers
- uWSGI with threading support
- Custom WSGI setup with proper Socket.IO integration

## Files in This Directory

- `socket_server.py`: Main Socket.IO initialization and event handling
- `events.py`: Watch operation event handlers
- `__init__.py`: Module initialization

## Debugging Tips

1. **Socket.IO Issues**: Enable logging with `SOCKETIO_LOGGING=True`
2. **Threading Issues**: Monitor thread count and check for deadlocks
3. **Playwright Issues**: Look for hanging processes and check browser cleanup
4. **Performance**: Monitor memory usage as threading can have different characteristics than green threads