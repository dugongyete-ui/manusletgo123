FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOSTNAME=sandbox
ENV PATH="/usr/local/bin:$PATH"
# Store Playwright browser binaries in a fixed system path so both root
# and the ubuntu user can access them after the image is built.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# ── Layer 1: Base system packages ──────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    sudo bc curl wget gnupg ca-certificates software-properties-common \
    xvfb x11vnc xterm supervisor \
    python3.10 python3.10-venv python3.10-dev python3-pip \
    nodejs \
    fonts-noto-cjk fonts-noto-color-emoji \
    # Chromium / Playwright browser runtime system deps
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    libpangocairo-1.0-0 libpango-1.0-0 \
    libgtk-3-0 \
    libx11-xcb1 libxcb1 libxcb-dri3-0 libxshmfence1 \
    libxext6 libxrender1 \
    libdbus-glib-1-2 libdbus-1-3 \
    libglib2.0-0 \
    # Additional deps for headless Chrome stability
    libvulkan1 libgl1-mesa-glx libgl1 \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 2: Google Chrome Stable (primary browser) ───────────────────────
# Ubuntu 22.04 ships chromium-browser as a snap stub that fails inside
# containers. We install the real Google Chrome from Google's apt repo.
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --batch --yes --dearmor \
            -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && ln -sf /usr/bin/google-chrome /usr/bin/chromium-browser \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 3: Python setup ─────────────────────────────────────────────────
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# ── Layer 4: Python packages (all in one layer, --break-system-packages    ─
#            needed on Ubuntu 22.04 + pip ≥ 23 / PEP 668)                  ─
RUN pip3 install --break-system-packages \
    # Sandbox HTTP server
    "fastapi>=0.121.2" \
    "uvicorn>=0.38.0" \
    "pydantic>=2.12.4" \
    "pydantic-settings>=2.12.0" \
    "python-multipart>=0.0.20" \
    "email-validator>=2.3.0" \
    # VNC websocket bridge
    websockify \
    # Playwright — pre-installed so _fix_chrome() fallback works instantly
    # without hitting pip permission errors at runtime.
    playwright

# ── Layer 5: Playwright Chromium browser binary (fallback if apt Chrome     ─
#            fails inside the running sandbox due to snap issues)             ─
RUN mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
    && python3 -m playwright install chromium \
    && python3 -m playwright install-deps chromium \
    # Make the directory world-readable so the ubuntu user can use it too
    && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}" \
    # Create a convenience symlink so chromium-browser also resolves to the
    # Playwright Chromium binary when Google Chrome is absent.
    && PWCHROME=$(find "${PLAYWRIGHT_BROWSERS_PATH}" -name "chrome" -type f 2>/dev/null | head -1) \
    && [ -n "$PWCHROME" ] \
       && ln -sf "$PWCHROME" /usr/bin/playwright-chromium \
       || echo "Playwright Chromium binary not found — will skip symlink"

# ── Layer 6: Application files ────────────────────────────────────────────
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY supervisord.conf ./supervisord.conf
COPY cdp_proxy.py ./cdp_proxy.py

# ── Layer 7: User setup ───────────────────────────────────────────────────
RUN useradd -m -s /bin/bash ubuntu \
    && echo "ubuntu ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && chown -R ubuntu:ubuntu /app \
    # Give ubuntu user access to playwright browsers installed as root
    && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}"

CMD ["/usr/bin/supervisord", "-n", "-c", "/app/supervisord.conf"]
