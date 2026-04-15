FROM ubuntu:latest

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y \
    python3 python3-pip python3-venv \
    curl git unzip wget \
    ffmpeg \
    # Playwright system deps
    libnspr4 libnss3 libatk-bridge2.0-0 \
    libcups2 libpango-1.0-0 libxss1 \
    libxrandr2 libasound2t64 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Timezone (configurable via TZ env var at runtime)
ENV TZ=UTC
RUN ln -sf /usr/share/zoneinfo/$TZ /etc/localtime

# Node.js 22 + Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@latest

# gh CLI (optional but useful)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Playwright Chromium
RUN PLAYWRIGHT_BROWSERS_PATH=/root/.playwright playwright install chromium

# Application code
COPY src/ /app/src-seed/
RUN cp -a /app/src-seed /app/src

# Workspace seed
COPY workspace-seed/CLAUDE.md /root/workspace/CLAUDE.md
RUN mkdir -p /root/.claude /app/config
RUN cp -a /root /root-seed

# Entrypoint
COPY start.sh /start.sh
RUN chmod +x /start.sh

LABEL maintainer="banana-bot-cc"
LABEL description="banana-bot-cc — self-hosted Claude Code Telegram bot"

CMD ["/start.sh"]
