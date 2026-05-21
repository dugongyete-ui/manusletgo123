FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOSTNAME=sandbox
ENV PATH="/usr/local/bin:$PATH"

# Base system packages (omit chromium-browser snap stub)
RUN apt-get update && apt-get install -y \
    sudo bc curl wget gnupg ca-certificates software-properties-common \
    xvfb x11vnc xterm socat supervisor \
    python3.10 python3.10-venv python3.10-dev python3-pip \
    nodejs \
    fonts-noto-cjk fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome Stable via the official Google apt repository.
# Ubuntu 22.04 ships chromium-browser as a snap stub that fails in
# Docker/e2b containers; installing from Google's repo gives a real binary.
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && ln -sf /usr/bin/google-chrome /usr/bin/chromium-browser \
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
