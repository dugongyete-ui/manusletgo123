FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOSTNAME=sandbox
ENV PATH="/usr/local/bin:$PATH"

RUN apt-get update && apt-get install -y \
    sudo bc curl wget gnupg software-properties-common \
    xvfb x11vnc xterm socat supervisor \
    python3.10 python3.10-venv python3.10-dev python3-pip \
    nodejs chromium-browser \
    fonts-noto-cjk fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
RUN pip3 install --break-system-packages websockify 2>/dev/null || pip3 install websockify

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY supervisord.conf ./supervisord.conf

RUN pip3 install \
    "fastapi>=0.121.2" \
    "uvicorn>=0.38.0" \
    "pydantic>=2.12.4" \
    "pydantic-settings>=2.12.0" \
    "python-multipart>=0.0.20" \
    "email-validator>=2.3.0"

RUN useradd -m -s /bin/bash ubuntu && \
    echo "ubuntu ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers && \
    chown -R ubuntu:ubuntu /app

CMD ["/usr/bin/supervisord", "-n", "-c", "/app/supervisord.conf"]
