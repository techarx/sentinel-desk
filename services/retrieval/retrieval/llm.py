"""Bedrock client (Converse API) with token and cost accounting.

Credentials: in the cluster the SDK reads short-lived credentials through
AWS_CONFIG_FILE -> credential_process (see deploy/apps/retrieval), refreshed
every 20 minutes by the dev machine. No keys in code or images.

Models must be US cross-region inference profiles (us.*): the lab account's
policy denies global routing, and the IAM role only allows the listed models.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Approximate on-demand USD prices per million tokens (input, output). Check the
# Bedrock pricing page for current values; used only for the cost estimate shown.
PRICES = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    seconds: float = 0.0
    by_model: dict[str, tuple[int, int]] = field(default_factory=dict)

    def add(self, model: str, inp: int, out: int, seconds: float) -> None:
        self.input_tokens += inp
        self.output_tokens += out
        self.calls += 1
        self.seconds += seconds
        prev = self.by_model.get(model, (0, 0))
        self.by_model[model] = (prev[0] + inp, prev[1] + out)

    def cost_usd(self) -> float | None:
        total = 0.0
        for model, (inp, out) in self.by_model.items():
            if model not in PRICES:
                return None
            pin, pout = PRICES[model]
            total += inp / 1e6 * pin + out / 1e6 * pout
        return total


class LLM:
    def __init__(self, model_id: str | None = None, usage: Usage | None = None):
        self.model_id = model_id or os.environ.get("LLM_MODEL_ID", DEFAULT_MODEL)
        self.usage = usage if usage is not None else Usage()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return self._client

    def complete(self, system: str, user: str, max_tokens: int = 800, temperature: float = 0.0) -> str:
        started = time.monotonic()
        resp = self.client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        u = resp.get("usage", {})
        self.usage.add(self.model_id, u.get("inputTokens", 0), u.get("outputTokens", 0), time.monotonic() - started)
        return "".join(block.get("text", "") for block in resp["output"]["message"]["content"])

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        """Ask for JSON; tolerate prose or code fences around it; retry once if it doesn't parse."""
        text = self.complete(system, user, max_tokens)
        try:
            return parse_json(text)
        except ValueError:
            text = self.complete(system, user + "\n\nReturn ONLY valid JSON, no other text.", max_tokens)
            return parse_json(text)


def parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in model output: {text[:200]!r}")
    return json.loads(match.group(0))
