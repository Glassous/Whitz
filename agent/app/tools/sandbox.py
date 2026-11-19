from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import docker
from docker.errors import DockerException
import httpx

from app.core.config import AgentSettings, get_settings

logger = logging.getLogger("whitz.agent.sandbox")

MAX_OUTPUT_CHARS = 16000


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    language: str = "python"
    mode: str = "disabled"
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:MAX_OUTPUT_CHARS],
            "stderr": self.stderr[:MAX_OUTPUT_CHARS],
            "timed_out": self.timed_out,
            "language": self.language,
            "mode": self.mode,
            "error": self.error,
        }


class SandboxExecutor(Protocol):
    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> SandboxResult: ...


def _build_command(language: str, code: str) -> list[str]:
    lang = (language or "python").strip().lower()
    if lang in ("py", "python", "python3"):
        return ["python3", "-I", "-c", code]
    if lang in ("sh", "bash", "shell"):
        return ["sh", "-c", code]
    if lang in ("js", "javascript", "node"):
        return ["node", "-e", code]
    raise ValueError(f"Unsupported sandbox language: {language}")


class DisabledSandboxExecutor:
    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> SandboxResult:
        return SandboxResult(
            exit_code=1,
            stdout="",
            stderr="",
            timed_out=False,
            language=language,
            mode="disabled",
            error="沙箱代码执行已禁用 (SANDBOX_MODE=disabled)。",
        )


class DockerSandboxExecutor:
    """Hardened ephemeral container executor (--network=none --read-only --memory=256m --cpus=0.5 --pids-limit=64)."""

    def __init__(
        self,
        *,
        image: str = "python:3.12-alpine",
        memory_limit: str = "256m",
        nano_cpus: int = 500_000_000,
        pids_limit: int = 64,
    ) -> None:
        self.image = image
        self.memory_limit = memory_limit
        self.nano_cpus = nano_cpus
        self.pids_limit = pids_limit

    def _run_sync(self, code: str, language: str, timeout_seconds: int) -> SandboxResult:
        try:
            cmd = _build_command(language, code)
        except ValueError as exc:
            return SandboxResult(
                exit_code=2,
                stdout="",
                stderr="",
                language=language,
                mode="docker",
                error=str(exc),
            )

        client = None
        container = None
        try:
            client = docker.from_env()
            container = client.containers.run(
                self.image,
                command=cmd,
                detach=True,
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                mem_limit=self.memory_limit,
                memswap_limit=self.memory_limit,
                nano_cpus=self.nano_cpus,
                pids_limit=self.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="65534:65534",
                working_dir="/tmp",
            )
            timed_out = False
            try:
                status = container.wait(timeout=timeout_seconds)
                exit_code = int(status.get("StatusCode", 1))
            except Exception:
                timed_out = True
                exit_code = 124
                try:
                    container.kill()
                except DockerException:
                    pass

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout[:MAX_OUTPUT_CHARS],
                stderr=stderr[:MAX_OUTPUT_CHARS],
                timed_out=timed_out,
                language=language,
                mode="docker",
                error="执行超时" if timed_out else None,
            )
        except DockerException as exc:
            logger.warning("Docker sandbox execution failed: %s", exc)
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr="",
                language=language,
                mode="docker",
                error=f"Docker 沙箱不可用: {exc}",
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> SandboxResult:
        return await asyncio.to_thread(self._run_sync, code, language, timeout_seconds)


class E2BSandboxExecutor:
    """Adapter for E2B cloud code execution sandboxes."""

    def __init__(self, api_key: str, base_url: str = "https://api.e2b.dev") -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
    ) -> SandboxResult:
        if not self.api_key:
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr="",
                language=language,
                mode="e2b",
                error="E2B_API_KEY 未配置。",
            )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds + 15.0)) as client:
                create_resp = await client.post(
                    f"{self.base_url}/sandboxes",
                    headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                    json={"templateID": "code-interpreter-v1", "timeout": max(30, timeout_seconds + 10)},
                )
                create_resp.raise_for_status()
                sandbox = create_resp.json()
                sandbox_id = sandbox.get("sandboxID") or sandbox.get("sandbox_id")
                if not sandbox_id:
                    raise RuntimeError("E2B did not return sandboxID")
                try:
                    exec_resp = await client.post(
                        f"{self.base_url}/sandboxes/{sandbox_id}/execute",
                        headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
                        json={"code": code, "language": language, "timeout": timeout_seconds},
                    )
                    exec_resp.raise_for_status()
                    data = exec_resp.json()
                    stdout = "\n".join(data.get("logs", {}).get("stdout") or []) if isinstance(data.get("logs"), dict) else str(data.get("stdout") or "")
                    stderr = "\n".join(data.get("logs", {}).get("stderr") or []) if isinstance(data.get("logs"), dict) else str(data.get("stderr") or "")
                    err = data.get("error")
                    return SandboxResult(
                        exit_code=1 if err else int(data.get("exit_code", 0)),
                        stdout=stdout[:MAX_OUTPUT_CHARS],
                        stderr=stderr[:MAX_OUTPUT_CHARS],
                        timed_out=False,
                        language=language,
                        mode="e2b",
                        error=str(err) if err else None,
                    )
                finally:
                    await client.delete(
                        f"{self.base_url}/sandboxes/{sandbox_id}",
                        headers={"X-API-Key": self.api_key},
                    )
        except Exception as exc:
            logger.warning("E2B sandbox execution failed: %s", exc)
            return SandboxResult(
                exit_code=1,
                stdout="",
                stderr="",
                language=language,
                mode="e2b",
                error=f"E2B 沙箱执行失败: {exc}",
            )


def get_sandbox_executor(settings: AgentSettings | None = None) -> SandboxExecutor:
    s = settings or get_settings()
    mode = (s.sandbox_mode or "disabled").strip().lower()
    if mode == "docker":
        return DockerSandboxExecutor(image=s.sandbox_docker_image)
    if mode == "e2b":
        return E2BSandboxExecutor(api_key=s.e2b_api_key)
    return DisabledSandboxExecutor()
