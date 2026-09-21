"""Server-only Moonshot adapter. No SDK globals, tools, shared chats, or secret traces."""
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import ValidationError

from backend.store import digest, timestamp


class ModelError(Exception):
    pass


def configuration():
    # Read just the authorized provider key; never import the Gym's other settings.
    sibling = Path(__file__).resolve().parents[2] / "big_learning_gym" / ".env"
    source = Path(os.environ.get("STANDOUT_LLM_ENV_FILE", str(sibling)))
    key = os.environ.get("MOONSHOT_API_KEY", "")
    if not key and source.is_file():
        key = dotenv_values(source).get("MOONSHOT_API_KEY") or ""
    return {"key": key, "model": os.environ.get("STANDOUT_LLM_MODEL", "kimi-k3"),
            "base_url": "https://api.moonshot.ai/v1", "max_tokens": 10000,
            "timeout_seconds": 240, "max_calls_per_day": int(os.environ.get("STANDOUT_MAX_MODEL_CALLS", "100"))}


class Moonshot:
    def __init__(self, store, config=None, transport=None):
        self.store = store
        self.config = config or configuration()
        self.transport = transport

    def describe(self):
        return {"configured": bool(self.config["key"]), "model": self.config["model"],
                "provider": "Moonshot", "mode": "live", "max_calls_per_day": self.config["max_calls_per_day"]}

    def complete(self, project_id, job_id, role, system, inputs, contract):
        if not self.config["key"]:
            raise ModelError("Kimi is not configured. Set MOONSHOT_API_KEY or STANDOUT_LLM_ENV_FILE on the server.")
        schema = contract.model_json_schema()
        system = system + "\nReturn exactly one JSON object matching this schema. No markdown fences.\n" + json.dumps(schema)
        prompt = json.dumps(inputs, ensure_ascii=False)
        if len(system) + len(prompt) > 110000:
            raise ModelError("The selected context is too large. Use shorter evidence passages for this round.")
        with self.store.connect(write=True) as conn:
            recent = [c for c in self.store.list(conn, "model_call") if c["created_at"][:10] == timestamp()[:10]]
            if len(recent) >= self.config["max_calls_per_day"]:
                raise ModelError("The daily model-call budget has been reached. Completed work is saved.")
            call = self.store.add(conn, "model_call", project_id, {
                "job_id": job_id, "role": role, "provider": "moonshot", "model": self.config["model"],
                "prompt_version": "standout-agents-v1", "scope": "selector_private" if role in ("selector_designer", "judge") else "applicant_private",
                "system": system, "inputs": inputs, "prompt_hash": digest([system, inputs]),
            })
        start = time.monotonic()
        usage, output, status, error = {}, None, "failed", None
        try:
            with httpx.Client(timeout=httpx.Timeout(self.config["timeout_seconds"], connect=20), transport=self.transport, follow_redirects=False) as client:
                response = client.post(self.config["base_url"] + "/chat/completions", headers={
                    "Authorization": "Bearer " + self.config["key"], "Content-Type": "application/json",
                }, json={"model": self.config["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                         "reasoning_effort": "low", "max_completion_tokens": self.config["max_tokens"],
                         "response_format": {"type": "json_object"}})
            if response.status_code >= 400:
                raise ModelError(f"Moonshot returned HTTP {response.status_code}. Check the provider account or retry later; no selection outcome was assigned.")
            data = response.json()
            usage = {k: v for k, v in data.get("usage", {}).items() if isinstance(v, (int, float, dict))}
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("Kimi reached the output limit. Completed stages are saved; try a narrower brief.")
            value = choice["message"].get("content") or ""
            output = contract.model_validate_json(value).model_dump(mode="json")
            status = "completed"
            return output, call["id"]
        except ModelError as exc:
            error = str(exc)
            raise
        except httpx.TransportError:
            error = "Moonshot could not be reached or timed out. Completed stages are saved."
            raise ModelError(error) from None
        except (ValueError, KeyError, IndexError, TypeError, ValidationError):
            # Do not persist invalid raw text or arbitrary provider error bodies.
            error = "Kimi returned an invalid structured response. Completed stages are saved; retry this round."
            raise ModelError(error) from None
        finally:
            with self.store.connect(write=True) as conn:
                self.store.add(conn, "model_result", project_id, {"call_id": call["id"], "job_id": job_id, "role": role,
                    "status": status, "output": output, "usage": usage, "error": error,
                    "elapsed_ms": round((time.monotonic() - start) * 1000)})
