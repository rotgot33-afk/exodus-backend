"""
Terminal Server - WebSocket-based real terminal
يستخدم pty لإنشاء terminal حقيقي (xterm.js compatible)
"""

import os
import pty
import select
import fcntl
import termios
import struct
import asyncio
import signal
from typing import Set

# Set of active terminal sessions
active_sessions: Set = set()


class TerminalSession:
    """A single terminal session with PTY"""

    def __init__(self, ws, cols: int = 80, rows: int = 24):
        self.ws = ws
        self.cols = cols
        self.rows = rows
        self.fd = None
        self.pid = None
        self.read_task = None

    async def start(self):
        """Start a new PTY session"""
        # Create PTY
        master_fd, slave_fd = pty.openpty()

        # Set window size
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        # Fork process
        pid = os.fork()
        if pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()

            # Set controlling terminal
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            # Redirect stdio
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)

            # Set environment
            os.environ["TERM"] = "xterm-256color"
            os.environ["PS1"] = "\\u@kali:\\w\\$ "

            # Execute shell
            os.execvp("/bin/bash", ["/bin/bash", "--login"])
        else:
            # Parent process
            os.close(slave_fd)
            self.fd = master_fd
            self.pid = pid
            active_sessions.add(self)

            # Start reading task
            self.read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        """Read from PTY and send to WebSocket"""
        try:
            while True:
                # Use asyncio to read without blocking
                await asyncio.sleep(0.01)
                try:
                    # Check if there's data
                    r, _, _ = select.select([self.fd], [], [], 0)
                    if r:
                        data = os.read(self.fd, 65536)
                        if not data:
                            break
                        # Send to WebSocket
                        await self.ws.send_bytes(data)
                except OSError:
                    break
        except Exception as e:
            print(f"Terminal read error: {e}")
        finally:
            await self.close()

    async def write(self, data: bytes):
        """Write to PTY (user input)"""
        if self.fd is not None:
            try:
                os.write(self.fd, data)
            except OSError:
                pass

    async def resize(self, cols: int, rows: int):
        """Resize terminal window"""
        self.cols = cols
        self.rows = rows
        if self.fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            try:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass

    async def close(self):
        """Close the terminal session"""
        if self in active_sessions:
            active_sessions.discard(self)

        if self.read_task and not self.read_task.done():
            self.read_task.cancel()

        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
                os.waitpid(self.pid, 0)
            except (OSError, ProcessLookupError):
                pass
            self.pid = None

        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

        try:
            await self.ws.close()
        except Exception:
            pass
