# EXODUS Backend - Render Deployment

Backend for CyberStrike Chat providing:
- 🤖 EXODUS-style agents management (all using Groq Llama-3.3-70B)
- 🖥️ Real WebSocket terminal (Kali Linux)
- 💬 Streaming chat with agents
- ⚡ Kali Linux command generation
- 🔧 Tools: nmap, sqlmap, nikto, whois, dig, netcat, tcpdump, hydra, john

## Deploy on Render

### Option 1: Use render.yaml (recommended)

1. Push this folder to a GitHub repo
2. Go to [dashboard.render.com](https://dashboard.render.com)
3. New → Web Service → Connect your repo
4. Render will detect `render.yaml` automatically
5. Add environment variable:
   - `GROQ_API_KEY` = your Groq API key
6. Deploy!

### Option 2: Manual setup

1. Push to GitHub
2. Render Dashboard → New Web Service
3. Connect repo
4. Settings:
   - **Runtime:** Docker
   - **Dockerfile Path:** `./Dockerfile`
   - **Plan:** Free
   - **Health Check:** `/health`
5. Environment Variables:
   - `GROQ_API_KEY` = your key (required)
6. Deploy

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/agents` | List all agents |
| GET | `/api/agents/{id}` | Get one agent |
| POST | `/api/agents` | Create agent |
| PUT | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |
| POST | `/api/agents/{id}/chat` | Chat with agent (SSE stream) |
| POST | `/api/agents/{id}/generate-command` | Generate Kali command |
| GET | `/api/tools` | List available tools |
| WS | `/ws/terminal` | Real terminal via WebSocket |

## Notes

- Render free tier sleeps after 15 min of inactivity
- First request after sleep takes ~30s to wake up
- 512MB RAM (sufficient for basic use)
- Data is ephemeral (lost on restart) - SQLite on /tmp
- All agents use the same model (Groq Llama-3.3-70B)
