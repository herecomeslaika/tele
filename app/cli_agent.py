"""A2A_min_v1 CLI Agent — command-line interface for interacting with the Gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Optional

import httpx


class CLIAgent:
    """CLI agent that communicates with the A2A_min_v1 Gateway."""

    def __init__(self, gateway_url: str = "http://localhost:8000",
                 api_key: Optional[str] = None, agent_id: Optional[str] = None):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id or f"cli-agent-{uuid.uuid4().hex[:8]}"
        self.session_id = f"session-{uuid.uuid4().hex[:8]}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.agent_id:
            headers["X-Agent-ID"] = self.agent_id
        return headers

    async def invoke(self, prompt: str, model: str = "deepseek-chat",
                     stream: bool = True, task_type: Optional[str] = None) -> None:
        """Send an INVOKE request and display streaming results."""
        corr_id = f"corr-{uuid.uuid4().hex[:8]}"

        envelope = {
            "version": "v1",
            "type": "INVOKE",
            "session_id": self.session_id,
            "corr_id": corr_id,
            "payload": {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "task_type": task_type,
            },
        }

        print(f"\n--- INVOKE ---")
        print(f"  session_id: {self.session_id}")
        print(f"  corr_id:    {corr_id}")
        print(f"  model:      {model}")
        print(f"  prompt:     {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
        print(f"--- RESPONSE ---\n")

        start = time.time()
        full_response = ""

        try:
            if stream:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(
                        "POST",
                        f"{self.gateway_url}/stream",
                        json=envelope,
                        headers=self._headers(),
                    ) as resp:
                        if resp.status_code != 200:
                            body = await resp.aread()
                            print(f"ERROR: HTTP {resp.status_code}: {body.decode()}")
                            return

                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                data = line[6:]
                                try:
                                    chunk = json.loads(data)
                                    msg_type = chunk.get("type", "")
                                    payload = chunk.get("payload", {})

                                    if msg_type == "STREAM_CHUNK":
                                        content = payload.get("content", "")
                                        print(content, end="", flush=True)
                                        full_response += content

                                    elif msg_type == "STREAM_END":
                                        reason = payload.get("reason", "")
                                        tokens = payload.get("total_tokens", 0)
                                        elapsed = (time.time() - start) * 1000
                                        print(f"\n\n--- END ---")
                                        print(f"  reason:       {reason}")
                                        print(f"  total_tokens: {tokens}")
                                        print(f"  duration_ms:  {elapsed:.0f}")
                                        print(f"  corr_id:      {corr_id}")

                                    elif msg_type == "ERROR":
                                        error_code = payload.get("error_code", "UNKNOWN")
                                        message = payload.get("message", "")
                                        print(f"\nERROR [{error_code}]: {message}")
                                        print(f"  corr_id: {corr_id}")

                                except json.JSONDecodeError:
                                    print(f"\n[Bad JSON: {data[:50]}]")
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.gateway_url}/invoke",
                        json=envelope,
                        headers=self._headers(),
                    )
                    result = resp.json()
                    if resp.status_code != 200:
                        print(f"ERROR: HTTP {resp.status_code}: {json.dumps(result, indent=2)}")
                    else:
                        print(json.dumps(result, indent=2, ensure_ascii=False))

        except httpx.ConnectError:
            print(f"ERROR: Cannot connect to gateway at {self.gateway_url}")
            print("  Make sure the gateway is running: python -m app.main")
        except Exception as e:
            print(f"ERROR: {e}")

    async def cancel(self, session_id: Optional[str] = None,
                      corr_id: Optional[str] = None) -> None:
        """Send a CANCEL request."""
        sid = session_id or self.session_id
        cid = corr_id or f"corr-{uuid.uuid4().hex[:8]}"

        envelope = {
            "version": "v1",
            "type": "CANCEL",
            "session_id": sid,
            "corr_id": cid,
            "payload": {"reason": "User requested cancel"},
        }

        print(f"\n--- CANCEL ---")
        print(f"  session_id: {sid}")
        print(f"  corr_id:    {cid}")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.gateway_url}/cancel",
                    json=envelope,
                    headers=self._headers(),
                )
                result = resp.json()
                print(f"  response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        except Exception as e:
            print(f"ERROR: {e}")

    async def heartbeat(self) -> None:
        """Send a HEARTBEAT."""
        envelope = {
            "version": "v1",
            "type": "HEARTBEAT",
            "session_id": self.session_id,
            "corr_id": f"hb-{uuid.uuid4().hex[:8]}",
            "payload": {},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.gateway_url}/heartbeat",
                    json=envelope,
                    headers=self._headers(),
                )
                result = resp.json()
                last_seen = result.get("payload", {}).get("last_seen", 0)
                print(f"HEARTBEAT OK — last_seen: {last_seen}")
        except Exception as e:
            print(f"HEARTBEAT ERROR: {e}")

    async def check_health(self) -> None:
        """Check gateway health."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.gateway_url}/health")
                result = resp.json()
                print(f"Gateway health: {json.dumps(result, indent=2)}")
        except Exception as e:
            print(f"Health check failed: {e}")

    async def get_metrics(self) -> None:
        """Get gateway metrics."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.gateway_url}/metrics")
                result = resp.json()
                print(f"Gateway metrics:\n{json.dumps(result, indent=2)}")
        except Exception as e:
            print(f"Metrics failed: {e}")


async def main():
    parser = argparse.ArgumentParser(description="A2A_min_v1 CLI Agent")
    parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway URL")
    parser.add_argument("--api-key", default=None, help="API key")
    parser.add_argument("--agent-id", default=None, help="Agent ID")

    sub = parser.add_subparsers(dest="command")

    # invoke
    invoke_p = sub.add_parser("invoke", help="Send an INVOKE request")
    invoke_p.add_argument("prompt", help="Prompt text")
    invoke_p.add_argument("--model", default="deepseek-chat", help="Model name")
    invoke_p.add_argument("--no-stream", action="store_true", help="Non-streaming mode")
    invoke_p.add_argument("--task-type", default=None, help="Task type for routing")

    # cancel
    cancel_p = sub.add_parser("cancel", help="Send a CANCEL request")
    cancel_p.add_argument("--session-id", default=None)
    cancel_p.add_argument("--corr-id", default=None)

    # heartbeat
    sub.add_parser("heartbeat", help="Send a HEARTBEAT")

    # health
    sub.add_parser("health", help="Check gateway health")

    # metrics
    sub.add_parser("metrics", help="Get gateway metrics")

    # interactive
    sub.add_parser("chat", help="Interactive chat mode")

    args = parser.parse_args()

    agent = CLIAgent(
        gateway_url=args.gateway,
        api_key=args.api_key,
        agent_id=args.agent_id,
    )

    if args.command == "invoke":
        await agent.invoke(args.prompt, model=args.model,
                            stream=not args.no_stream, task_type=args.task_type)

    elif args.command == "cancel":
        await agent.cancel(session_id=args.session_id, corr_id=args.corr_id)

    elif args.command == "heartbeat":
        await agent.heartbeat()

    elif args.command == "health":
        await agent.check_health()

    elif args.command == "metrics":
        await agent.get_metrics()

    elif args.command == "chat":
        print("A2A_min_v1 Interactive Chat (type 'quit' to exit, 'cancel' to cancel)")
        print(f"Gateway: {args.gateway}")
        print(f"Agent ID: {agent.agent_id}")
        print()
        while True:
            try:
                prompt = input("You> ").strip()
                if not prompt:
                    continue
                if prompt == "quit":
                    break
                if prompt == "cancel":
                    await agent.cancel()
                    continue
                if prompt == "heartbeat":
                    await agent.heartbeat()
                    continue
                if prompt == "metrics":
                    await agent.get_metrics()
                    continue
                await agent.invoke(prompt)
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())