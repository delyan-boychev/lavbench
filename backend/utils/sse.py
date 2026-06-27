from flask import Response, stream_with_context


def sse_response(event_generator):
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(
        stream_with_context(event_generator()),
        mimetype="text/event-stream",
        headers=headers,
    )
