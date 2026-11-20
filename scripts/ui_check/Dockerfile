# The capture image: the official Playwright image (browsers included) plus the pinned
# Python packages, built once by run.sh and reused by every capture phase
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# The image's non-root user; run.sh also runs it as the caller's uid so /out stays theirs
USER pwuser
