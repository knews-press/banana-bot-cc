<div align="center">
  <img src="docs/logo.png" alt="banana-bot-cc" width="120" />
  <h1>banana-bot-cc</h1>
  <p><strong>Self-hosted Claude Code Telegram Bot + Web UI</strong></p>
  <p>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" /></a>
    <img src="https://img.shields.io/badge/docker-compose-blue" alt="Docker Compose" />
    <img src="https://img.shields.io/badge/claude-code-orange" alt="Claude Code" />
  </p>
</div>

---

> *A banana ripens where it lives. So does this bot.*

banana-bot-cc is built around a simple idea: **your AI assistant should get better over time, shaped by you, running on your terms.** The bot has full access to its own source code and can rewrite itself — fix a bug, add a tool, adjust its behavior — directly from a chat message. Every change is live immediately. No rebuild, no redeploy. Over weeks and months it accumulates memory, learns your preferences, and evolves into something that fits you specifically. Not a generic cloud chatbot. Yours.

Everything runs on your own server via Docker Compose. No data leaves your infrastructure.

## Features

| | |
|---|---|
| 🤖 **Telegram Bot** | Chat with Claude Code via Telegram — sessions, tools, extended thinking |
| 🌐 **Web UI** | Browser-based chat with Monaco editor, real-time streaming, tool call inspector |
| 🧠 **Persistent Memory** | Elasticsearch-backed memories with full-text search, versioning and conversation history |
| 🕸️ **Knowledge Graph** | Optional Neo4j graph with automatic entity extraction (NER) |
| 📊 **Cost Tracking** | Per-session, per-day, per-model token and cost tracking |
| 📎 **File Uploads** | Send PDFs, images, audio, spreadsheets via Telegram — indexed and searchable |
| 🎙️ **Voice Messages** | Voice messages are automatically transcribed and passed to Claude |
| 🔒 **Approval Mode** | Optional tool-by-tool approval via Telegram inline buttons |
| 🔄 **Self-Improvement** | The bot runs from a mounted volume and can modify its own source code |

## Requirements

- Server with **Docker** and **Docker Compose** (4 GB RAM minimum, 8 GB recommended with graph)
- [Anthropic account](https://claude.ai) with Claude Pro or Max subscription
- [Telegram Bot Token](https://t.me/BotFather)
- Your Telegram User ID (get it from [@userinfobot](https://t.me/userinfobot))

## Quick Start

```bash
# Clone
git clone https://github.com/knews-press/banana-bot-cc.git
cd banana-bot-cc

# Configure
cp .env.example .env
nano .env

# Start
docker compose up -d

# Authenticate Claude Code (one-time setup)
docker compose exec backend claude login

# Open Telegram, find your bot, send /start
```

## Optional Services

banana-bot-cc uses Docker Compose profiles to keep the default footprint small:

```bash
# Minimal: Telegram bot only (no Web UI)
docker compose up -d backend mysql elasticsearch

# + Knowledge Graph (Neo4j)
docker compose --profile graph up -d

# + Private Web Search (SearXNG)
docker compose --profile search up -d

# + HTTPS Reverse Proxy (Caddy)
docker compose --profile proxy up -d

# Everything
docker compose --profile graph --profile search --profile proxy up -d
```

## Configuration

All settings live in `.env`. Copy `.env.example` to get started:

### Required

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `TELEGRAM_BOT_USERNAME` | Your bot's username (without @) |
| `ALLOWED_USERS` | Your Telegram user ID (comma-separated for multiple users) |
| `MYSQL_ROOT_PASSWORD` | MySQL root password |
| `MYSQL_PASSWORD` | MySQL app user password |
| `JWT_SECRET` | Secret for Web UI sessions (min 32 chars) |

### Optional

| Variable | Description |
|----------|-------------|
| `INSTANCE_NAME` | Bot display name in Web UI (default: `banana-bot`) |
| `PUBLIC_URL` | Public URL for the Web UI (e.g. `https://bot.example.com`) |
| `NEO4J_PASSWORD` | Enables knowledge graph (`--profile graph` required) |
| `GH_PAT` | GitHub Personal Access Token — enables `gh` CLI for Claude |
| `OPENAI_API_KEY` | Enables image generation + TTS via OpenAI |
| `GEMINI_API_KEY` | Enables image generation + TTS via Gemini |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | Enables magic-link login for Web UI |

### System Prompt

Edit `config/system-prompt.md` to customize Claude's personality, role, and behavior.  
Changes take effect on the next message — **no restart needed**.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/new` | Start a new session |
| `/session list` | List all sessions |
| `/session load <id>` | Resume a previous session |
| `/status` | Current session info |
| `/model` | Switch Claude model |
| `/mode` | Toggle yolo / plan / approve mode |
| `/memory search <query>` | Search memories |
| `/memory list` | List all memories |
| `/me` | View and edit your profile |
| `/stop` | Abort current execution |
| `/help` | Full command reference |

## Web UI

The frontend runs on port `3000` and provides:

- **Chat** — full-featured chat with streaming, tool call inspector, and session management
- **Memory Browser** — search, view and manage all memories
- **Knowledge Graph** — interactive 3D graph visualization (requires `--profile graph`)
- **Files** — browse uploaded files
- **Settings** — preferences, model selection, approval mode

Access at `http://localhost:3000/<instance-name>` (or your public URL).

## Architecture

```
Telegram ─────────────────────────────────┐
                                          ▼
                              backend (FastAPI + bot, :8080)
                                 │        │
                          Claude Code SDK │
                                 │        │
              ┌──────────────────┼────────┼────────────────┐
              ▼                  ▼        ▼                 ▼
           MySQL          Elasticsearch  Neo4j*         SearXNG*
        (sessions,        (memories,   (knowledge       (web search)
       cost tracking)    conversations)  graph)

                              backend
                                 │
                          frontend (Next.js, :3000)
                                 │
                        Caddy reverse proxy*
                                 │
                      https://your-domain.com

* optional (Docker Compose profiles)
```

## Self-Improvement

banana-bot-cc mounts its own source code as a Docker volume. This means Claude can read, edit and improve the bot's code directly — and the changes take effect immediately without rebuilding the image.

```bash
# Mount source code for live editing
volumes:
  - ./backend/src:/app/src  # add to docker-compose.yml override
```

> ⚠️ Use `/mode approve` if you want to review tool calls before Claude executes them.

## License

[MIT](LICENSE) — © 2026 banana-bot-cc contributors
