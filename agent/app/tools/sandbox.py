from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import docker
from docker.errors import DockerException
import httpx

from app.core.config import AgentSettings, get_settings

logger = logging.getLogger("whitz.agent.sandbox")

MAX_OUTPUT_CHARS = 16000
MAX_HARVEST_FILES = 5
MAX_HARVEST_FILE_BYTES = 5 * 1024 * 1024


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    language: str = "python"
    mode: str = "disabled"
    error: str | None = None
    output_files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:MAX_OUTPUT_CHARS],
            "stderr": self.stderr[:MAX_OUTPUT_CHARS],
            "timed_out": self.timed_out,
            "language": self.language,
            "mode": self.mode,
            "error": self.error,
        }
        if self.output_files:
            out["output_files"] = [
                {k: v for k, v in f.items() if k != "content_b64"}
                for f in self.output_files
            ]
        return out


class SandboxExecutor(Protocol):
    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
        workspace_files: dict[str, bytes] | None = None,
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


def _safe_filename(name: str) -> str:
    cleaned = os.path.basename((name or "").replace("\\", "/")).strip()
    return cleaned if cleaned and cleaned not in (".", "..") else "file"


class DisabledSandboxExecutor:
    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
        workspace_files: dict[str, bytes] | None = None,
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
    """Hardened ephemeral container executor with optional read-only /workspace/input and /workspace/output harvesting."""

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

    def _run_sync(
        self,
        code: str,
        language: str,
        timeout_seconds: int,
        workspace_files: dict[str, bytes] | None = None,
        container_holder: dict[str, Any] | None = None,
    ) -> SandboxResult:
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
        staging_dir: str | None = None
        volumes: dict[str, dict[str, str]] | None = None
        output_dir: Path | None = None
        try:
            if workspace_files is not None:
                staging_dir = tempfile.mkdtemp(prefix="whitz-sbx-")
                input_dir = Path(staging_dir) / "input"
                output_dir = Path(staging_dir) / "output"
                input_dir.mkdir(parents=True, exist_ok=True)
                output_dir.mkdir(parents=True, exist_ok=True)
                os.chmod(output_dir, 0o777)
                for fname, raw in workspace_files.items():
                    safe = _safe_filename(fname)
                    (input_dir / safe).write_bytes(raw)
                volumes = {
                    str(input_dir): {"bind": "/workspace/input", "mode": "ro"},
                    str(output_dir): {"bind": "/workspace/output", "mode": "rw"},
                }

            client = docker.from_env()
            run_kwargs: dict[str, Any] = {
                "command": cmd,
                "detach": True,
                "network_disabled": True,
                "read_only": True,
                "tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
                "mem_limit": self.memory_limit,
                "memswap_limit": self.memory_limit,
                "nano_cpus": self.nano_cpus,
                "pids_limit": self.pids_limit,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "user": "65534:65534",
                "working_dir": "/tmp",
            }
            if volumes:
                run_kwargs["volumes"] = volumes

            container = client.containers.run(self.image, **run_kwargs)
            if container_holder is not None:
                container_holder["container"] = container

            timed_out = False
            try:
                status = container.wait(timeout=timeout_seconds)
                exit_code = int(status.get("StatusCode", 1))
            except Exception as wait_exc:
                err_name = type(wait_exc).__name__.lower()
                if "timeout" in err_name or "timed out" in str(wait_exc).lower():
                    timed_out = True
                    exit_code = 124
                    try:
                        container.kill()
                    except DockerException:
                        pass
                else:
                    raise

            def _read_bounded_logs(*, stdout_flag: bool, stderr_flag: bool) -> str:
                max_bytes = MAX_OUTPUT_CHARS * 4
                raw = container.logs(stdout=stdout_flag, stderr=stderr_flag, stream=True)
                if isinstance(raw, (bytes, bytearray)):
                    return bytes(raw[:max_bytes]).decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
                buf = bytearray()
                for chunk in raw:
                    if isinstance(chunk, bytes):
                        need = max_bytes - len(buf)
                        if need <= 0:
                            break
                        buf.extend(chunk[:need])
                return buf.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]

            stdout = _read_bounded_logs(stdout_flag=True, stderr_flag=False)
            stderr = _read_bounded_logs(stdout_flag=False, stderr_flag=True)

            harvested: list[dict[str, Any]] = []
            if output_dir is not None and output_dir.exists():
                for child in sorted(output_dir.iterdir()):
                    if len(harvested) >= MAX_HARVEST_FILES:
                        break
                    if child.is_file() and not child.is_symlink():
                        sz = child.stat().st_size
                        if 0 < sz <= MAX_HARVEST_FILE_BYTES:
                            raw_bytes = child.read_bytes()
                            harvested.append(
                                {
                                    "filename": child.name,
                                    "size_bytes": sz,
                                    "content_b64": base64.b64encode(raw_bytes).decode("ascii"),
                                }
                            )

            return SandboxResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                language=language,
                mode="docker",
                error="执行超时" if timed_out else None,
                output_files=harvested,
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
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
        workspace_files: dict[str, bytes] | None = None,
    ) -> SandboxResult:
        holder: dict[str, Any] = {}
        try:
            return await asyncio.to_thread(
                self._run_sync,
                code,
                language,
                timeout_seconds,
                workspace_files,
                holder,
            )
        except asyncio.CancelledError:
            c = holder.get("container")
            if c is not None:
                try:
                    await asyncio.to_thread(c.remove, force=True)
                except Exception:
                    pass
            raise


class E2BSandboxExecutor:
    """Adapter for E2B cloud code execution sandboxes (supports both v2 sandbox-host and v1 endpoints)."""

    def __init__(self, api_key: str, base_url: str = "https://api.e2b.dev") -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")

    async def execute(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int = 30,
        workspace_files: dict[str, bytes] | None = None,
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
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds + 15.0), trust_env=False) as client:
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
                domain = str(sandbox.get("domain") or "").strip()
                envd_token = str(sandbox.get("envdAccessToken") or "").strip()
                exec_url = (
                    f"https://49999-{sandbox_id}.{domain}/execute"
                    if domain
                    else f"{self.base_url}/sandboxes/{sandbox_id}/execute"
                )
                exec_headers = {"Content-Type": "application/json"}
                if envd_token:
                    exec_headers["X-Access-Token"] = envd_token
                else:
                    exec_headers["X-API-Key"] = self.api_key

                try:
                    exec_payload: dict[str, Any] = {
                        "code": code,
                        "language": language,
                        "timeout": timeout_seconds,
                    }
                    if workspace_files:
                        exec_payload["files"] = {
                            f"/workspace/input/{_safe_filename(k)}": base64.b64encode(v).decode("ascii")
                            for k, v in workspace_files.items()
                        }
                    exec_resp = await client.post(
                        exec_url,
                        headers=exec_headers,
                        json=exec_payload,
                    )
                    exec_resp.raise_for_status()
                    data = exec_resp.json()
                    stdout = (
                        "\n".join(data.get("logs", {}).get("stdout") or [])
                        if isinstance(data.get("logs"), dict)
                        else str(data.get("stdout") or "")
                    )
                    stderr = (
                        "\n".join(data.get("logs", {}).get("stderr") or [])
                        if isinstance(data.get("logs"), dict)
                        else str(data.get("stderr") or "")
                    )
                    err = data.get("error")
                    harvested: list[dict[str, Any]] = []
                    for item in data.get("results") or []:
                        if isinstance(item, dict) and item.get("png") and len(harvested) < MAX_HARVEST_FILES:
                            raw_b64 = str(item["png"])
                            harvested.append(
                                {
                                    "filename": f"sandbox_plot_{len(harvested) + 1}.png",
                                    "size_bytes": len(base64.b64decode(raw_b64)),
                                    "content_b64": raw_b64,
                                }
                            )
                    return SandboxResult(
                        exit_code=1 if err else int(data.get("exit_code", 0)),
                        stdout=stdout[:MAX_OUTPUT_CHARS],
                        stderr=stderr[:MAX_OUTPUT_CHARS],
                        timed_out=False,
                        language=language,
                        mode="e2b",
                        error=str(err) if err else None,
                        output_files=harvested,
                    )
                finally:
                    try:
                        await client.delete(
                            f"{self.base_url}/sandboxes/{sandbox_id}",
                            headers={"X-API-Key": self.api_key},
                        )
                    except Exception as cleanup_exc:
                        logger.debug("E2B sandbox cleanup failed for %s: %s", sandbox_id, cleanup_exc)
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
