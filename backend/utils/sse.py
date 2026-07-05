from flask import stream_with_context


def sse_response(event_generator):
    headers = [
        ("Cache-Control", "no-cache"),
        ("X-Accel-Buffering", "no"),
        ("Connection", "keep-alive"),
        ("Content-Type", "text/event-stream"),
    ]
    return stream_with_context(event_generator()), 200, headers
