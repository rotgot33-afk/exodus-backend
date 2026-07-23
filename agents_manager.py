"""
EXODUS-style Agents Manager
إدارة الوكلاء باستخدام Groq (Llama-3.3-70B) للجميع
يدعم: Supabase (عند توفره) أو SQLite (fallback)
"""

import os
import json
import time
import uuid
import asyncio
import sqlite3
from typing import Optional, List, Dict, Any

# ============== Groq Client ==============

from groq import AsyncGroq

# Initialize Groq client - try multiple sources
GROQ_API_KEY = (
    os.environ.get("GROQ_API_KEY") or
    os.environ.get("groq_api_key") or
    os.environ.get("GROQ_KEY") or
    ""
)

# Debug info
print(f"DEBUG: GROQ_API_KEY set: {bool(GROQ_API_KEY)}", flush=True)
print(f"DEBUG: Env vars with GROQ: {[k for k in os.environ if 'GROQ' in k.upper()]}", flush=True)

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Default model (all agents use the same model)
DEFAULT_MODEL = "llama-3.3-70b-versatile"


# ============== Supabase Client ==============

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
supabase = None
supabase_enabled = False

try:
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase_enabled = True
        print(f"✅ Supabase enabled: {SUPABASE_URL}", flush=True)
    else:
        print("⚠️ Supabase not configured (SUPABASE_URL or SUPABASE_KEY missing)", flush=True)
except Exception as e:
    print(f"❌ Supabase init failed: {e}", flush=True)
    supabase_enabled = False


def init_supabase():
    """Re-check Supabase (called on startup)"""
    global supabase, supabase_enabled
    if not supabase_enabled:
        try:
            if SUPABASE_URL and SUPABASE_KEY:
                from supabase import create_client, Client
                supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                supabase_enabled = True
                print(f"✅ Supabase re-initialized: {SUPABASE_URL}", flush=True)
        except Exception as e:
            print(f"❌ Supabase re-init failed: {e}", flush=True)


# ============== SQLite Fallback ==============

DB_PATH = "/tmp/exodus_agents.db"


def init_db():
    """Initialize SQLite database (fallback when Supabase not available)"""
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


# Default agents
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
    if supabase_enabled:
        try:
            # Check if agents exist
            result = supabase.table("agents").select("id").limit(1).execute()
            if not result.data:
                # Insert defaults
                for agent in DEFAULT_AGENTS:
                    supabase.table("agents").insert({
                        "name": agent["name"],
                        "specialty": agent["specialty"],
                        "system_prompt": agent["system_prompt"],
                        "model": DEFAULT_MODEL,
                    }).execute()
                print("✅ Default agents seeded to Supabase", flush=True)
        except Exception as e:
            print(f"⚠️ Supabase seed failed: {e}", flush=True)
    else:
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


# Run seed on import
seed_default_agents()


# ============== Agent CRUD ==============

def list_agents() -> List[Dict[str, Any]]:
    """List all agents"""
    if supabase_enabled:
        try:
            result = supabase.table("agents").select("*").order("created_at", desc=True).execute()
            return result.data or []
        except Exception as e:
            print(f"Supabase list_agents failed: {e}", flush=True)
            return _sqlite_list_agents()
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


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Get a single agent"""
    if supabase_enabled:
        try:
            result = supabase.table("agents").select("*").eq("id", agent_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"Supabase get_agent failed: {e}", flush=True)
            return _sqlite_get_agent(agent_id)
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


def create_agent(name: str, specialty: str, system_prompt: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Create a new agent"""
    if supabase_enabled:
        try:
            result = supabase.table("agents").insert({
                "name": name,
                "specialty": specialty,
                "system_prompt": system_prompt,
                "model": model,
            }).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            print(f"Supabase create_agent failed: {e}", flush=True)
            return _sqlite_create_agent(name, specialty, system_prompt, model)
    return _sqlite_create_agent(name, specialty, system_prompt, model)


def _sqlite_create_agent(name: str, specialty: str, system_prompt: str, model: str) -> Dict[str, Any]:
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


def update_agent(agent_id: str, name: str = None, specialty: str = None, system_prompt: str = None, model: str = None) -> Optional[Dict[str, Any]]:
    """Update an agent"""
    agent = get_agent(agent_id)
    if not agent:
        return None

    updates = {}
    if name is not None: updates["name"] = name
    if specialty is not None: updates["specialty"] = specialty
    if system_prompt is not None: updates["system_prompt"] = system_prompt
    if model is not None: updates["model"] = model

    if supabase_enabled:
        try:
            result = supabase.table("agents").update(updates).eq("id", agent_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"Supabase update_agent failed: {e}", flush=True)
            return _sqlite_update_agent(agent_id, agent, name, specialty, system_prompt, model)
    return _sqlite_update_agent(agent_id, agent, name, specialty, system_prompt, model)


def _sqlite_update_agent(agent_id, agent, name, specialty, system_prompt, model):
    now = time.time()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """UPDATE agents SET 
           name = ?, specialty = ?, system_prompt = ?, model = ?, updated_at = ? 
           WHERE id = ?""",
        (
            name or agent["name"],
            specialty or agent["specialty"],
            system_prompt or agent["system_prompt"],
            model or agent["model"],
            now,
            agent_id
        )
    )
    conn.commit()
    conn.close()
    return _sqlite_get_agent(agent_id)


def delete_agent(agent_id: str):
    """Delete an agent"""
    if supabase_enabled:
        try:
            supabase.table("agents").delete().eq("id", agent_id).execute()
            return
        except Exception as e:
            print(f"Supabase delete_agent failed: {e}", flush=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()


# ============== Chat with Agent ==============

async def chat_with_agent(agent_id: str, messages: list, stream: bool = True):
    """Stream chat with an agent using Groq"""
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")

    if not groq_client:
        raise RuntimeError("GROQ_API_KEY not set")

    # Build messages with agent's system prompt
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


# ============== Generate Kali Command ==============

async def generate_kali_command(agent_id: str, user_request: str):
    """Generate a Kali Linux command based on user request"""
    agent = get_agent(agent_id)
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
