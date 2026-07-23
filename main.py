"""
EXODUS Backend API - FastAPI Server
يقدم:
- REST API لإدارة الوكلاء (CRUD) - يحفظ في Supabase
- WebSocket للـ terminal الحقيقي عبر Segfault.net
- Chat streaming مع الوكلاء عبر Groq
- /api/execute - تنفيذ مباشر من الشات
- /api/cron - استقبال cron pings لإبقاء الخدمة نشطة
"""

import os
import json
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from agents_manager import (
    list_agents, get_agent, create_agent, update_agent, delete_agent,
    chat_with_agent, generate_kali_command, DEFAULT_MODEL,
    init_supabase, supabase_enabled
)
from segfault_manager import segfault

# ============== App Setup ==============

app = FastAPI(
    title="EXODUS Backend",
    description="Backend for EXODUS agents + Terminal + Kali Linux + Segfault",
    version="2.0.0"
)

# CORS - allow Vercel frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase on startup
@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup"""
    logger.info("Starting EXODUS Backend v2.0...")
    init_supabase()
    logger.info(f"Supabase enabled: {supabase_enabled}")
    logger.info(f"Groq configured: {bool(os.environ.get('GROQ_API_KEY'))}")
    # Don't connect to Segfault on startup - connect on demand
    logger.info("Segfault will connect on demand (each SSH = new VM)")


# ============== Models ==============

class AgentCreate(BaseModel):
    name: str
    specialty: str
    system_prompt: str
    model: str = DEFAULT_MODEL


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    specialty: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list
    stream: bool = True


class CommandRequest(BaseModel):
    user_request: str


class ExecuteRequest(BaseModel):
    command: str
    agent_id: Optional[str] = None
    timeout: int = 30


class CronRequest(BaseModel):
    key: Optional[str] = None


# ============== Routes ==============

@app.get("/health")
async def health():
    """Health check endpoint"""
    segfault_health = await segfault.health_check()
    return {
        "status": "online",
        "service": "exodus-backend",
        "version": "2.0.0",
        "model": DEFAULT_MODEL,
        "groq_configured": bool(os.environ.get("GROQ_API_KEY")),
        "supabase_enabled": supabase_enabled,
        "segfault": {
            "connected": segfault_health.get("connected", False),
            "host": segfault_health.get("host", "segfault.net"),
        },
        "active_terminals": len(active_terminals),
    }


# ============== Agents ==============

@app.get("/api/agents")
async def api_list_agents():
    """List all agents"""
    return {"agents": list_agents()}


@app.get("/api/agents/{agent_id}")
async def api_get_agent(agent_id: str):
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.post("/api/agents")
async def api_create_agent(agent: AgentCreate):
    return create_agent(
        name=agent.name,
        specialty=agent.specialty,
        system_prompt=agent.system_prompt,
        model=agent.model
    )


@app.put("/api/agents/{agent_id}")
async def api_update_agent(agent_id: str, agent: AgentUpdate):
    updated = update_agent(
        agent_id,
        name=agent.name,
        specialty=agent.specialty,
        system_prompt=agent.system_prompt,
        model=agent.model
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return updated


@app.delete("/api/agents/{agent_id}")
async def api_delete_agent(agent_id: str):
    delete_agent(agent_id)
    return {"deleted": True}


# ============== Chat ==============

@app.post("/api/agents/{agent_id}/chat")
async def api_chat(agent_id: str, req: ChatRequest):
    """Chat with an agent (streaming SSE)"""
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    async def event_stream():
        try:
            async for chunk in chat_with_agent(agent_id, req.messages, stream=True):
                sse_data = f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]})}\n\n"
                yield sse_data.encode("utf-8")
            yield b"data: [DONE]\n\n"
        except Exception as e:
            err_data = f"data: {json.dumps({'error': str(e)})}\n\n"
            yield err_data.encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/agents/{agent_id}/generate-command")
async def api_generate_command(agent_id: str, req: CommandRequest):
    """Generate a Kali Linux command based on user request"""
    try:
        result = await generate_kali_command(agent_id, req.user_request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== Direct Execution (NEW) ==============

@app.post("/api/execute")
async def api_execute(req: ExecuteRequest):
    """Execute a command directly on Segfault"""
    logger.info(f"Execute request: {req.command[:100]}...")

    # Optional: verify agent_id exists
    if req.agent_id:
        agent = get_agent(req.agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

    # Execute on Segfault
    rc, output = await segfault.execute(req.command, timeout=req.timeout)

    return {
        "command": req.command,
        "output": output,
        "exit_code": rc,
        "success": rc == 0,
        "executed_at": str(asyncio.get_event_loop().time()),
    }


@app.get("/api/segfault/health")
async def api_segfault_health():
    """Check Segfault connection health"""
    return await segfault.health_check()


@app.post("/api/segfault/connect")
async def api_segfault_connect():
    """Force connect to Segfault"""
    success = await segfault.connect()
    return {"connected": success, "error": segfault.last_error if not success else None}


# ============== Cron Endpoint (NEW) ==============

@app.post("/api/cron")
async def api_cron(req: CronRequest = None):
    """
    Endpoint for cron-job.org to ping.
    Keeps both Render and Segfault alive.
    """
    logger.info("📡 Cron ping received")

    # Optional API key check
    cron_key = os.environ.get("CRON_KEY", "")
    if cron_key and req and req.key != cron_key:
        raise HTTPException(status_code=403, detail="Invalid cron key")

    # Wake up Segfault (new SSH connection = new VM, but that's how Segfault works)
    try:
        rc, output = await segfault.execute("echo 'cron-keepalive' && date", timeout=15)
        segfault_status = "alive" if rc == 0 else "error"
    except Exception as e:
        segfault_status = f"error: {str(e)}"
        output = ""

    return {
        "status": "alive",
        "service": "exodus-backend",
        "timestamp": str(asyncio.get_event_loop().time()),
        "segfault": segfault_status,
        "active_terminals": len(active_terminals),
    }


@app.get("/api/cron")
async def api_cron_get():
    """GET version for simple cron pings"""
    return await api_cron(CronRequest())


# ============== Tools ==============

@app.get("/api/tools")
async def api_list_tools():
    """List available Kali tools"""
    return {
        "tools": [
            {"name": "nmap", "description": "Network scanner", "category": "recon"},
            {"name": "sqlmap", "description": "SQL injection tool", "category": "web"},
            {"name": "nikto", "description": "Web server scanner", "category": "web"},
            {"name": "whois", "description": "Domain information", "category": "recon"},
            {"name": "dig", "description": "DNS lookup", "category": "recon"},
            {"name": "netcat", "description": "Network utility (nc)", "category": "network"},
            {"name": "tcpdump", "description": "Packet capture", "category": "network"},
            {"name": "hydra", "description": "Password cracker", "category": "crack"},
            {"name": "john", "description": "Password cracker", "category": "crack"},
            {"name": "traceroute", "description": "Network path trace", "category": "network"},
            {"name": "ssh", "description": "SSH client (for connecting elsewhere)", "category": "network"},
        ],
        "note": "All tools run on Segfault.net (real Kali Linux root)"
    }


# ============== WebSocket Terminal ==============

# Active terminal sessions (for monitoring)
active_terminals = set()


@app.websocket("/ws/terminal")
async def ws_terminal(ws: WebSocket):
    """
    WebSocket endpoint for real terminal access.
    Routes commands to Segfault.net via SSH.

    How it works:
    1. User types in browser → WebSocket → Render
    2. Render opens SSH to Segfault.net
    3. Each command = new SSH connection (Segfault creates new VM per SSH)
    4. Output sent back through WebSocket

    Note: For interactive commands (vim, top, etc.), we use PTY mode
    """
    await ws.accept()
    terminal_id = id(ws)
    active_terminals.add(terminal_id)

    # Get initial size from query params
    cols = int(ws.query_params.get("cols", "80"))
    rows = int(ws.query_params.get("rows", "24"))

    logger.info(f"Terminal WebSocket connected (id={terminal_id})")

    try:
        # Send welcome
        await ws.send_text("\r\n\x1b[1;32m🛡️ EXODUS Terminal → Segfault.net\x1b[0m\r\n")
        await ws.send_text("\x1b[1;33m📡 Connected to Kali Linux (root@segfault.net)\x1b[0m\r\n")
        await ws.send_text("\x1b[2mℹ️  Each command opens a new SSH session (Segfault behavior)\x1b[0m\r\n")
        await ws.send_text("\x1b[2mℹ️  Persistent storage: /sec\x1b[0m\r\n\r\n")

        # Test connection
        rc, output = await segfault.execute("whoami && hostname && pwd", timeout=15)
        if rc == 0:
            await ws.send_text(f"\x1b[1;32m✅ Connected as: {output.strip()}\x1b[0m\r\n\r\n")
        else:
            await ws.send_text(f"\x1b[1;31m❌ Connection test failed: {output[:200]}\x1b[0m\r\n\r\n")

        # Interactive loop
        current_input = ""
        prompt = "root@segfault:~# "

        while True:
            await ws.send_text(prompt)

            # Receive input
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            if "text" in msg and msg["text"] is not None:
                # Text input (could be a full command or single char)
                text = msg["text"]

                # Check if it's a control message (JSON)
                if text.startswith("{") and text.endswith("}"):
                    try:
                        data = json.loads(text)
                        if data.get("type") == "resize":
                            cols = int(data.get("cols", 80))
                            rows = int(data.get("rows", 24))
                        elif data.get("type") == "close":
                            break
                        continue
                    except json.JSONDecodeError:
                        pass

                # Treat as command input
                # Echo back what user typed (for visual feedback)
                await ws.send_text(text)

                # Handle special keys
                if text == "\r" or text == "\n":
                    # Execute the command
                    if current_input.strip():
                        await ws.send_text("\r\n")

                        # Don't execute 'clear' via SSH, just clear screen
                        if current_input.strip() == "clear":
                            await ws.send_text("\x1b[2J\x1b[H")
                            current_input = ""
                            continue

                        # Execute on Segfault
                        rc, output = await segfault.execute(current_input, timeout=60)

                        # Send output
                        if output:
                            await ws.send_text(output)
                            if not output.endswith("\n"):
                                await ws.send_text("\r\n")

                        # Show exit code if non-zero
                        if rc != 0:
                            await ws.send_text(f"\x1b[1;31m[exit code: {rc}]\x1b[0m\r\n")

                    current_input = ""
                elif text == "\x03":  # Ctrl+C
                    await ws.send_text("^C\r\n")
                    current_input = ""
                elif text == "\x7f":  # Backspace
                    if current_input:
                        current_input = current_input[:-1]
                        await ws.send_text("\b \b")
                elif text.isprintable() and len(text) == 1:
                    current_input += text
                elif len(text) > 1:
                    # Multi-char paste - execute as full command
                    current_input = text.strip()
                    await ws.send_text(current_input + "\r\n")
                    if current_input:
                        rc, output = await segfault.execute(current_input, timeout=60)
                        if output:
                            await ws.send_text(output)
                            if not output.endswith("\n"):
                                await ws.send_text("\r\n")
                        if rc != 0:
                            await ws.send_text(f"\x1b[1;31m[exit code: {rc}]\x1b[0m\r\n")
                    current_input = ""

            elif "bytes" in msg and msg["bytes"] is not None:
                # Binary data
                try:
                    text = msg["bytes"].decode("utf-8", errors="replace")
                    # Handle same as text
                    if text == "\r" or text == "\n":
                        if current_input.strip():
                            await ws.send_text("\r\n")
                            rc, output = await segfault.execute(current_input, timeout=60)
                            if output:
                                await ws.send_text(output)
                                if not output.endswith("\n"):
                                    await ws.send_text("\r\n")
                            if rc != 0:
                                await ws.send_text(f"\x1b[1;31m[exit code: {rc}]\x1b[0m\r\n")
                        current_input = ""
                    else:
                        current_input += text
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info(f"Terminal WebSocket disconnected (id={terminal_id})")
    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
    finally:
        active_terminals.discard(terminal_id)


# ============== Main ==============

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=60,
    )
