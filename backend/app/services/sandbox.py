from __future__ import annotations

import asyncio
import sys
from typing import Any


async def run_replication_probe() -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "print('replication harness ready')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return {
        "returncode": process.returncode,
        "stdout": stdout.decode().strip(),
        "stderr": stderr.decode().strip(),
    }
