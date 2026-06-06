FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/workers/gpu

COPY apps/api/requirements/base.txt /tmp/aidublaj-api-requirements.txt
RUN pip install -r /tmp/aidublaj-api-requirements.txt

COPY workers/gpu/requirements-seedvc.txt /tmp/seedvc-requirements.txt
RUN python -m venv --system-site-packages /opt/seedvc-venv \
    && /opt/seedvc-venv/bin/pip install -r /tmp/seedvc-requirements.txt

CMD ["python", "app/main.py"]
