"""QA-only launcher: run uvicorn on the Windows Selector event loop.

The Proactor event loop (uvicorn's win32 default) has a known flaw where an
abrupt client disconnect during accept() raises WinError 64 in its
accept-coroutine and kills the event loop. Chrome headless screenshots open
and close connections abruptly, which triggers this. The classic Selector
event loop tolerates those disconnects.
"""
import asyncio
import os
import sys

import uvicorn

if sys.platform != "win32":
    raise SystemExit("This launcher is only meant for Windows QA runs.")

# Override with QA_SERVER_PORT when 8000 is occupied by another process.
PORT = int(os.environ.get("QA_SERVER_PORT", "8000"))

config = uvicorn.Config("app.main:app", host="127.0.0.1", port=PORT, log_level="info")
config.get_loop_factory = lambda use_subprocess=False: asyncio.SelectorEventLoop

uvicorn.Server(config).run()
