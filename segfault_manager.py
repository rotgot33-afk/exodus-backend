"""
Segfault SSH Manager
يدير اتصال SSH مع Segfault.net (free Kali Linux root shell)
- يستخدم sshpass للمصادقة بكلمة المرور "segfault"
- يحافظ على جلسة SSH نشطة
- ينفذ الأوامر ويعيد النتائج
"""

import os
import asyncio
import logging
import time
import shlex
from typing import Optional, Tuple
import subprocess

logger = logging.getLogger(__name__)

# Segfault configuration
SEGFAULT_HOST = "segfault.net"
SEGFAULT_USER = "root"
SEGFAULT_PASSWORD = os.environ.get("SEGFAULT_PASSWORD", "segfault")
SEGFAULT_TOKEN = os.environ.get("SEGFAULT_TOKEN", "")  # optional token for upgrade
SSH_TIMEOUT = 30  # seconds for SSH operations
KEEPALIVE_INTERVAL = 60  # seconds between keepalive pings


class SegfaultManager:
    """Manages SSH connection to Segfault.net"""

    def __init__(self):
        self.last_activity = 0
        self.connected = False
        self.last_error = None
        self.session_start = 0
        self._keepalive_task = None

    async def connect(self) -> bool:
        """Test connection to Segfault (each SSH is a new VM in Segfault)"""
        try:
            logger.info(f"Connecting to Segfault ({SEGFAULT_HOST})...")
            # In Segfault, every SSH connection creates a new VM
            # So we test connectivity by running a simple command
            result = await self.execute("echo 'Segfault connected' && whoami && hostname")
            if result[0] == 0:
                self.connected = True
                self.session_start = time.time()
                self.last_activity = time.time()
                logger.info(f"Segfault connected: {result[1][:200]}")
                # Start keepalive task
                if self._keepalive_task is None:
                    self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                return True
            else:
                self.connected = False
                self.last_error = result[1]
                return False
        except Exception as e:
            logger.error(f"Segfault connection failed: {e}")
            self.connected = False
            self.last_error = str(e)
            return False

    async def execute(self, command: str, timeout: int = SSH_TIMEOUT) -> Tuple[int, str]:
        """
        Execute a command on Segfault via SSH.
        Returns (exit_code, output).
        """
        # Escape command for SSH
        escaped_cmd = command.replace("'", "'\\''")

        # Build SSH command with sshpass
        ssh_cmd = [
            "sshpass",
            "-p", SEGFAULT_PASSWORD,
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-o", f"ServerAliveInterval={KEEPALIVE_INTERVAL}",
            "-o", "ServerAliveCountMax=3",
            "-o", "LogLevel=ERROR",
            f"{SEGFAULT_USER}@{SEGFAULT_HOST}",
            f"bash -c '{escaped_cmd}'"
        ]

        try:
            # Run SSH command asynchronously
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return (124, f"Command timed out after {timeout}s")

            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                output += stderr.decode("utf-8", errors="replace")

            self.last_activity = time.time()
            return (proc.returncode or 0, output)

        except FileNotFoundError:
            return (127, "sshpass not installed. Install with: apt-get install sshpass")
        except Exception as e:
            return (1, f"SSH error: {str(e)}")

    async def execute_persistent(self, command: str) -> Tuple[int, str]:
        """Execute a command and store output in /sec for persistence"""
        # Use /sec which is persistent across Segfault sessions
        storage_file = f"/sec/output_{int(time.time())}.txt"
        full_cmd = f"{command} 2>&1 | tee {storage_file}"
        return await self.execute(full_cmd)

    async def _keepalive_loop(self):
        """Background task to keep Segfault alive"""
        while True:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                # Check if we've been inactive
                idle_time = time.time() - self.last_activity
                if idle_time < KEEPALIVE_INTERVAL:
                    continue  # Recent activity, no need for keepalive

                logger.info("Sending keepalive to Segfault...")
                rc, _ = await self.execute("echo 'keepalive' > /dev/null", timeout=15)
                if rc == 0:
                    self.connected = True
                    logger.info("Segfault keepalive OK")
                else:
                    self.connected = False
                    logger.warning(f"Segfault keepalive failed (rc={rc})")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Keepalive error: {e}")

    async def health_check(self) -> dict:
        """Check Segfault health"""
        try:
            rc, output = await self.execute("echo ok && date && uname -a", timeout=15)
            return {
                "connected": rc == 0,
                "host": SEGFAULT_HOST,
                "last_activity": self.last_activity,
                "session_start": self.session_start,
                "output": output[:500] if rc == 0 else None,
                "error": output[:200] if rc != 0 else None,
            }
        except Exception as e:
            return {
                "connected": False,
                "host": SEGFAULT_HOST,
                "error": str(e),
            }

    async def disconnect(self):
        """Stop keepalive task"""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
            self._keepalive_task = None
        self.connected = False


# Singleton instance
segfault = SegfaultManager()
