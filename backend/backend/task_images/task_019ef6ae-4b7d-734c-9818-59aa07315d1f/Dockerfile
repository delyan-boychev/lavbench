FROM pytorch/pytorch:2.6.0-cuda12.6-cudnn9-runtime
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY hf_cache /hf_cache
