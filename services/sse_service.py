import json
import queue
import threading

from flask import Response, stream_with_context


_listeners = []
_lock = threading.Lock()


def broadcast_event(event_type, data):
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _lock:
        stale_listeners = []
        for listener in _listeners:
            try:
                listener.put(payload)
            except Exception:
                stale_listeners.append(listener)

        for listener in stale_listeners:
            if listener in _listeners:
                _listeners.remove(listener)


def listener_count():
    with _lock:
        return len(_listeners)


def stream_response():
    def event_generator():
        listener = queue.Queue()
        with _lock:
            _listeners.append(listener)

        print(f"[SSE] Client connected. Total listeners: {listener_count()}")

        try:
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ': heartbeat\n\n'
        finally:
            with _lock:
                if listener in _listeners:
                    _listeners.remove(listener)
            print(f"[SSE] Client disconnected. Total listeners: {listener_count()}")

    return Response(
        stream_with_context(event_generator()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )
