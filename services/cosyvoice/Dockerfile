FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ffmpeg \
      git \
      sox \
      libsox-dev \
      build-essential \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/services/cosyvoice

COPY services/cosyvoice/requirements.txt /tmp/requirements.txt
COPY services/cosyvoice/minimal_inference_requirements.txt /tmp/minimal_inference_requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt \
    && python -m pip install setuptools==70.0.0 wheel numpy==1.26.4 cython \
    && python -m pip install --no-build-isolation -r /tmp/minimal_inference_requirements.txt \
    && python -m pip install --force-reinstall torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
