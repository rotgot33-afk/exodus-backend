"""
EXODUS-style Agents Manager
إدارة الوكلاء باستخدام Groq (Llama-3.3-70B) للجميع
يدعم: Supabase عبر REST API (httpx) أو SQLite (fallback)
"""

import os
import json
import time
import uuid
import asyncio
import sqlite3
from typing import Optional, List, Dict, Any

import httpx
from groq import AsyncGroq

# ============== Groq Client ==============

GROQ_API_KEY = (
    os.environ.get("GROQ_API_KEY") or
    os.environ.get("groq_api_key") or
    os.environ.get("GROQ_KEY") or
    ""
)

print(f"DEBUG: GROQ_API_KEY set: {bool(GROQ_API_KEY)}", flush=True)

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
DEFAULT_MODEL = "llama-3.3-70b-versatile"


# ============== Supabase via REST API ==============

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
supabase_enabled = bool(SUPABASE_URL and SUPABASE_KEY)

print(f"DEBUG: Supabase enabled: {supabase_enabled} ({SUPABASE_URL})", flush=True)


def init_supabase():
    """Re-check Supabase (called on startup)"""
    global supabase_enabled
    supabase_enabled = bool(SUPABASE_URL and SUPABASE_KEY)
    print(f"Supabase status: {'enabled' if supabase_enabled else 'disabled (using SQLite fallback)'}", flush=True)


async def supabase_request(method: str, table: str, data: dict = None, filters: dict = None, order: str = None) -> Optional[Any]:
    """Make a request to Supabase REST API"""
    if not supabase_enabled:
        return None

    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # Add filters as query params
    params = {}
    if filters:
        for k, v in filters.items():
            params[k] = f"eq.{v}"
    if order:
        params["order"] = order

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(url, headers=headers, params=params, json=data)
            elif method == "PATCH":
                resp = await client.patch(url, headers=headers, params=params, json=data)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params)
            else:
                return None

            if resp.status_code in (200, 201):
                return resp.json() if resp.text else []
            else:
                print(f"Supabase {method} {table} failed: {resp.status_code} {resp.text[:200]}", flush=True)
                return None
    except Exception as e:
        print(f"Supabase request error: {e}", flush=True)
        return None


# ============== SQLite Fallback ==============

DB_PATH = "/tmp/exodus_agents.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            model TEXT DEFAULT 'llama-3.3-70b-versatile',
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()


init_db()

DEFAULT_AGENTS = [
    {
        "name": "Recon Specialist",
        "specialty": "reconnaissance",
        "system_prompt": "أنت وكيل متخصص في الاستطلاع (Reconnaissance). تجمع المعلومات عن الأهداف باستخدام أدوات مثل nmap, whois, dnsenum. تشرح كل خطوة وتسأل عن إذن المستخدم قبل تنفيذ أي فحص."
    },
    {
        "name": "Web Pentester",
        "specialty": "web_pentest",
        "system_prompt": "أنت وكيل متخصص في اختبار اختراق تطبيقات الويب. تستخدم sqlmap, nikto, gobuster. تركّز على OWASP Top 10 وتشرح الثغرات بالتفصيل."
    },
    {
        "name": "Network Analyst",
        "specialty": "network_analysis",
        "system_prompt": "أنت وكيل متخصص في تحليل الشبكات. تستخدم tcpdump, tshark, netstat. تحلل حركة المرور وتكتشف الأنشطة المشبوهة."
    },
    {
        "name": "Password Cracker",
        "specialty": "password_cracking",
        "system_prompt": "أنت وكيل متخصص في كسر كلمات المرور. تستخدم john, hydra. تشرح أنواع الهجمات (dictionary, brute force, rainbow tables) وتطلب إذناً صريحاً قبل أي عملية."
    },
]


def seed_default_agents():
    """Create default agents if database is empty"""
    async def _seed():
        if supabase_enabled:
            result = await supabase_request("GET", "agents", filters={"id": "not.is.null"}, order="created_at.desc")
            if result is not None and len(result) == 0:
                for agent in DEFAULT_AGENTS:
                    await supabase_request("POST", "agents", data={
                        "name": agent["name"],
                        "specialty": agent["specialty"],
                        "system_prompt": agent["system_prompt"],
                        "model": DEFAULT_MODEL,
                    })
                print("✅ Default agents seeded to Supabase", flush=True)
            return

        # SQLite fallback
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM agents")
        count = c.fetchone()[0]
        if count == 0:
            for agent in DEFAULT_AGENTS:
                agent_id = str(uuid.uuid4())
                now = time.time()
                c.execute(
                    "INSERT INTO agents (id, name, specialty, system_prompt, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (agent_id, agent["name"], agent["specialty"], agent["system_prompt"], DEFAULT_MODEL, now, now)
                )
            conn.commit()
        conn.close()

    try:
        asyncio.get_event_loop().run_until_complete(_seed())
    except RuntimeError:
        # No event loop yet, create one
        asyncio.run(_seed())


# ============== Agent CRUD ==============

async def list_agents() -> List[Dict[str, Any]]:
    if supabase_enabled:
        result = await supabase_request("GET", "agents", order="created_at.desc")
        if result is not None:
            return result
    return _sqlite_list_agents()


def _sqlite_list_agents() -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, specialty, system_prompt, model, created_at, updated_at FROM agents ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "name": r[1], "specialty": r[2],
            "system_prompt": r[3], "model": r[4],
            "created_at": r[5], "updated_at": r[6]
        }
        for r in rows
    ]


async def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    if supabase_enabled:
        result = await supabase_request("GET", "agents", filters={"id": agent_id})
        if result is not None:
            return result[0] if result else None
    return _sqlite_get_agent(agent_id)


def _sqlite_get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, specialty, system_prompt, model, created_at, updated_at FROM agents WHERE id = ?", (agent_id,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {
        "id": r[0], "name": r[1], "specialty": r[2],
        "system_prompt": r[3], "model": r[4],
        "created_at": r[5], "updated_at": r[6]
    }


async def create_agent(name: str, specialty: str, system_prompt: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    if supabase_enabled:
        result = await supabase_request("POST", "agents", data={
            "name": name, "specialty": specialty,
            "system_prompt": system_prompt, "model": model,
        })
        if result is not None:
            return result[0] if result else {}
    return _sqlite_create_agent(name, specialty, system_prompt, model)


def _sqlite_create_agent(name, specialty, system_prompt, model):
    agent_id = str(uuid.uuid4())
    now = time.time()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO agents (id, name, specialty, system_prompt, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (agent_id, name, specialty, system_prompt, model, now, now)
    )
    conn.commit()
    conn.close()
    return _sqlite_get_agent(agent_id)


async def update_agent(agent_id: str, name: str = None, specialty: str = None, system_prompt: str = None, model: str = None) -> Optional[Dict[str, Any]]:
    agent = await get_agent(agent_id)
    if not agent:
        return None

    updates = {}
    if name is not None: updates["name"] = name
    if specialty is not None: updates["specialty"] = specialty
    if system_prompt is not None: updates["system_prompt"] = system_prompt
    if model is not None: updates["model"] = model

    if supabase_enabled:
        result = await supabase_request("PATCH", "agents", data=updates, filters={"id": agent_id})
        if result is not None:
            return result[0] if result else None

    # SQLite fallback
    now = time.time()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """UPDATE agents SET name = ?, specialty = ?, system_prompt = ?, model = ?, updated_at = ? WHERE id = ?""",
        (name or agent["name"], specialty or agent["specialty"],
         system_prompt or agent["system_prompt"], model or agent["model"], now, agent_id)
    )
    conn.commit()
    conn.close()
    return _sqlite_get_agent(agent_id)


async def delete_agent(agent_id: str):
    if supabase_enabled:
        await supabase_request("DELETE", "agents", filters={"id": agent_id})
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()


# ============== Chat ==============

async def chat_with_agent(agent_id: str, messages: list, stream: bool = True):
    agent = await get_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")

    if not groq_client:
        raise RuntimeError("GROQ_API_KEY not set")

    full_messages = [{"role": "system", "content": agent["system_prompt"]}]
    full_messages.extend(messages)

    if stream:
        stream_resp = await groq_client.chat.completions.create(
            model=agent["model"],
            messages=full_messages,
            stream=True,
            temperature=0.7,
            max_tokens=2048,
        )
        async for chunk in stream_resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    else:
        resp = await groq_client.chat.completions.create(
            model=agent["model"],
            messages=full_messages,
            temperature=0.7,
            max_tokens=2048,
        )
        yield resp.choices[0].message.content


async def generate_kali_command(agent_id: str, user_request: str):
    agent = await get_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")

    if not groq_client:
        raise RuntimeError("GROQ_API_KEY not set")

    prompt = f"""أنت {agent['name']} متخصص في {agent['specialty']}.

طلب المستخدم: {user_request}

ولّد أمر Kali Linux مناسب. يجب أن تكون الإجابة بصيغة JSON بالشكل التالي فقط:
{{
    "command": "الأمر الفعلي",
    "explanation": "شرح موجز لما يفعله الأمر",
    "warning": "تحذيرات إن وجدت (أو فارغ)",
    "safe_to_run": true/false
}}

قواعد:
- استخدم الأدوات المتاحة على Segfault.net: nmap, sqlmap, nikto, whois, dig, netcat, tcpdump, hydra, john
- لا تستخدم metasploit
- ضع في اعتبارك أن الأمر سيُنفّذ على Segfault (root Kali Linux)
- إذا كان الطلب خطيراً، اضبط safe_to_run على false
"""

    resp = await groq_client.chat.completions.create(
        model=agent["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=500,
    )

    content = resp.choices[0].message.content.strip()
    try:
        import re
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except json.JSONDecodeError:
        pass
    return {
        "command": content,
        "explanation": "تم توليد الأمر",
        "warning": "",
        "safe_to_run": True
    }


# ============== Sync wrappers for FastAPI ==============

def list_agents_sync() -> List[Dict[str, Any]]:
    """Sync wrapper for list_agents"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, can't use run_until_complete
            # Use SQLite fallback for sync call
            return _sqlite_list_agents()
        return loop.run_until_complete(list_agents())
    except RuntimeError:
        return asyncio.run(list_agents())


# Initialize on import
try:
    seed_default_agents()
except Exception as e:
    print(f"Seed agents warning: {e}", flush=True)
