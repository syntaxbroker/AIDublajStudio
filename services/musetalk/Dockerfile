FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      bash \
      curl \
      ffmpeg \
      git \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/services/musetalk

COPY services/musetalk/requirements.txt /tmp/requirements.txt
COPY services/musetalk/minimal_inference_requirements.txt /tmp/minimal_inference_requirements.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/requirements.txt \
    && python -m pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128 \
    && python -m pip install --no-build-isolation chumpy==0.70 \
    && python -m pip install -r /tmp/minimal_inference_requirements.txt
