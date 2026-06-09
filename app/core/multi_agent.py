"""A2A_min_v1 Multi-Agent Manager — agent registry, delegation, and coordination."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from app.adapters.router import ProviderRouter
from app.core.errors import AGENT_NOT_FOUND, DELEGATION_FAILED
from app.core.logger import setup_logger, log_event
from app.core.security import SecurityManager
from app.models.envelope import Envelope, MessageType

logger = setup_logger("multi_agent")


@dataclass
class AgentProfile:
    agent_id: str
    name: str
    roles: list[str] = field(default_factory=lambda: ["worker"])
    capabilities: list[str] = field(default_factory=list)
    endpoint: Optional[str] = None
    status: str = "online"
    max_concurrent_tasks: int = 5
    current_tasks: int = 0
    api_key: Optional[str] = None
    registered_at: float = field(default_factory=time.time)


@dataclass
class DelegationRecord:
    delegation_id: str
    source_agent: str
    target_agent: str
    task: str
    pattern: str = "single"  # "single" | "fan-out" | "fan-in" | "pipeline"
    status: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    sub_delegations: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    session_id: Optional[str] = None


@dataclass
class AgentRegistry:
    """Registry of agent profiles with capability and role lookups."""

    agents: dict[str, AgentProfile] = field(default_factory=dict)

    def register(self, profile: AgentProfile) -> None:
        self.agents[profile.agent_id] = profile
        log_event(logger, "agent.registered", state=f"agent_id={profile.agent_id}")

    def deregister(self, agent_id: str) -> bool:
        if agent_id in self.agents:
            del self.agents[agent_id]
            log_event(logger, "agent.deregistered", state=f"agent_id={agent_id}")
            return True
        return False

    def get(self, agent_id: str) -> Optional[AgentProfile]:
        return self.agents.get(agent_id)

    def list_agents(self) -> list[AgentProfile]:
        return list(self.agents.values())

    def find_by_capability(self, capability: str) -> list[AgentProfile]:
        return [
            a for a in self.agents.values()
            if capability in a.capabilities and a.status == "online"
        ]

    def find_by_role(self, role: str) -> list[AgentProfile]:
        return [
            a for a in self.agents.values()
            if role in a.roles and a.status == "online"
        ]

    def find_available(self, capability: Optional[str] = None,
                       role: Optional[str] = None) -> Optional[AgentProfile]:
        """Find an available agent matching capability and/or role with capacity."""
        candidates = list(self.agents.values())
        if capability:
            candidates = [a for a in candidates if capability in a.capabilities]
        if role:
            candidates = [a for a in candidates if role in a.roles]
        candidates = [a for a in candidates if a.status == "online"
                      and a.current_tasks < a.max_concurrent_tasks]
        if not candidates:
            return None
        candidates.sort(key=lambda a: a.current_tasks)
        return candidates[0]


@dataclass
class MultiAgentManager:
    """Orchestrates agent registration, delegation, and coordination."""

    registry: AgentRegistry = field(default_factory=AgentRegistry)
    delegations: dict[str, DelegationRecord] = field(default_factory=dict)

    def register_agent(self, profile: AgentProfile,
                       security: Optional[SecurityManager] = None) -> str:
        """Register an agent and optionally create its API key."""
        if security:
            api_key = f"ak-{uuid.uuid4().hex[:24]}"
            profile.api_key = api_key
            security.register_agent(
                agent_id=profile.agent_id,
                roles=profile.roles,
            )
        self.registry.register(profile)
        return profile.agent_id

    def deregister_agent(self, agent_id: str) -> bool:
        return self.registry.deregister(agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentProfile]:
        return self.registry.get(agent_id)

    def list_agents(self) -> list[AgentProfile]:
        return self.registry.list_agents()

    async def handle_delegate(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Process an AGENT_DELEGATE envelope.

        Validates target agent exists, creates a DelegationRecord,
        routes the task through the provider, and yields AGENT_RESPONSE.
        """
        payload = envelope.payload
        target_agent_id = payload.get("target_agent", "")
        task = payload.get("task", "")
        pattern = payload.get("pattern", "single")
        source_agent = payload.get("source_agent", envelope.session_id)

        # Validate target agent
        target = self.registry.get(target_agent_id)
        if not target:
            log_event(logger, "delegate.agent_not_found",
                      error_code="AGENT_NOT_FOUND",
                      state=f"target={target_agent_id}")
            yield Envelope(
                version="v1",
                type=MessageType.ERROR,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                seq=envelope.seq,
                payload={
                    "error_code": "AGENT_NOT_FOUND",
                    "message": f"Agent '{target_agent_id}' not found in registry",
                },
            ).model_dump()
            return

        if target.status != "online":
            log_event(logger, "delegate.agent_offline",
                      error_code="DELEGATION_FAILED",
                      state=f"target={target_agent_id},status={target.status}")
            yield Envelope(
                version="v1",
                type=MessageType.ERROR,
                session_id=envelope.session_id,
                corr_id=envelope.corr_id,
                seq=envelope.seq,
                payload={
                    "error_code": "DELEGATION_FAILED",
                    "message": f"Agent '{target_agent_id}' is offline (status={target.status})",
                },
            ).model_dump()
            return

        # Create delegation record
        delegation_id = f"del-{uuid.uuid4().hex[:12]}"
        record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=target_agent_id,
            task=task,
            pattern=pattern,
            status="running",
            session_id=envelope.session_id,
        )
        self.delegations[delegation_id] = record
        target.current_tasks += 1

        log_event(logger, "delegate.created",
                  state=f"delegation_id={delegation_id},target={target_agent_id}")

        # Route task through provider if router available
        if router and router.routes:
            try:
                provider_name, provider_adapter = router.select(
                    session_id=envelope.session_id,
                    model=target.capabilities[0] if target.capabilities else None,
                )
                chunks = []
                async for event in provider_adapter.invoke(
                    prompt=task,
                    model=payload.get("model", "mock-model"),
                ):
                    if event.type == "chunk":
                        chunks.append(event.content or "")
                    elif event.type == "end":
                        break
                    elif event.type == "error":
                        record.status = "failed"
                        record.error = event.error_msg or "Provider error"
                        record.completed_at = time.time()
                        log_event(logger, "delegate.provider_error",
                                  error_code="DELEGATION_FAILED",
                                  state=f"delegation_id={delegation_id}")
                        yield Envelope(
                            version="v1",
                            type=MessageType.ERROR,
                            session_id=envelope.session_id,
                            corr_id=envelope.corr_id,
                            seq=envelope.seq,
                            payload={
                                "error_code": "DELEGATION_FAILED",
                                "message": f"Provider error: {event.error_msg}",
                                "delegation_id": delegation_id,
                            },
                        ).model_dump()
                        target.current_tasks = max(0, target.current_tasks - 1)
                        return

                result_text = "".join(chunks) if chunks else "completed"
                record.status = "completed"
                record.result = result_text
                record.completed_at = time.time()
            except Exception as e:
                record.status = "failed"
                record.error = str(e)
                record.completed_at = time.time()
                log_event(logger, "delegate.provider_error",
                          error_code="DELEGATION_FAILED",
                          state=f"delegation_id={delegation_id}")
                yield Envelope(
                    version="v1",
                    type=MessageType.ERROR,
                    session_id=envelope.session_id,
                    corr_id=envelope.corr_id,
                    seq=envelope.seq,
                    payload={
                        "error_code": "DELEGATION_FAILED",
                        "message": f"Provider error during delegation: {e}",
                        "delegation_id": delegation_id,
                    },
                ).model_dump()
                target.current_tasks = max(0, target.current_tasks - 1)
                return
        else:
            record.status = "completed"
            record.result = task
            record.completed_at = time.time()

        target.current_tasks = max(0, target.current_tasks - 1)

        log_event(logger, "delegate.completed",
                  state=f"delegation_id={delegation_id},status={record.status}")

        yield Envelope(
            version="v1",
            type=MessageType.AGENT_RESPONSE,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=envelope.seq,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "target_agent": target_agent_id,
                "result": record.result or "",
                "status": record.status,
            },
        ).model_dump()

    def handle_response(self, envelope: Envelope) -> Optional[DelegationRecord]:
        """Process an AGENT_RESPONSE envelope — updates the delegation record."""
        payload = envelope.payload
        delegation_id = payload.get("delegation_id", "")
        record = self.delegations.get(delegation_id)

        if not record:
            log_event(logger, "response.unknown_delegation",
                      state=f"delegation_id={delegation_id}")
            return None

        record.result = payload.get("result", record.result)
        record.status = payload.get("status", record.status)
        record.completed_at = time.time()

        target = self.registry.get(record.target_agent)
        if target:
            target.current_tasks = max(0, target.current_tasks - 1)

        log_event(logger, "response.received",
                  state=f"delegation_id={delegation_id},status={record.status}")
        return record

    async def handle_fan_out(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Fan-out delegation: distribute task to multiple agents concurrently.

        Payload must contain:
          - target_agents: list of agent_id strings
          - task: the task description to send to all targets

        Each target agent receives the same task independently.
        Results are collected and returned as a combined AGENT_RESPONSE.
        """
        payload = envelope.payload
        target_agent_ids = payload.get("target_agents", [])
        task = payload.get("task", "")
        source_agent = payload.get("source_agent", envelope.session_id)

        if not target_agent_ids:
            yield Envelope(
                version="v1", type=MessageType.ERROR,
                session_id=envelope.session_id, corr_id=envelope.corr_id,
                seq=envelope.seq,
                payload={"error_code": "BAD_REQUEST", "message": "target_agents list is empty"},
            ).model_dump()
            return

        # Validate all target agents exist
        missing = [aid for aid in target_agent_ids if not self.registry.get(aid)]
        if missing:
            yield Envelope(
                version="v1", type=MessageType.ERROR,
                session_id=envelope.session_id, corr_id=envelope.corr_id,
                seq=envelope.seq,
                payload={
                    "error_code": "AGENT_NOT_FOUND",
                    "message": f"Agents not found: {missing}",
                },
            ).model_dump()
            return

        # Check all targets are online
        offline = [aid for aid in target_agent_ids
                   if self.registry.get(aid) and self.registry.get(aid).status != "online"]
        if offline:
            yield Envelope(
                version="v1", type=MessageType.ERROR,
                session_id=envelope.session_id, corr_id=envelope.corr_id,
                seq=envelope.seq,
                payload={
                    "error_code": "DELEGATION_FAILED",
                    "message": f"Agents offline: {offline}",
                },
            ).model_dump()
            return

        # Create parent delegation record
        delegation_id = f"fan-{uuid.uuid4().hex[:12]}"
        parent_record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=",".join(target_agent_ids),
            task=task,
            pattern="fan-out",
            status="running",
            session_id=envelope.session_id,
        )
        self.delegations[delegation_id] = parent_record

        log_event(logger, "fanout.created",
                  state=f"delegation_id={delegation_id},targets={len(target_agent_ids)}")

        # Dispatch to each target agent concurrently
        sub_results: list[dict] = []
        tasks_coro = []

        for target_id in target_agent_ids:
            target = self.registry.get(target_id)
            if target:
                target.current_tasks += 1

            sub_del_id = f"sub-{uuid.uuid4().hex[:8]}"
            sub_record = DelegationRecord(
                delegation_id=sub_del_id,
                source_agent=source_agent,
                target_agent=target_id,
                task=task,
                pattern="single",
                status="running",
                session_id=envelope.session_id,
            )
            self.delegations[sub_del_id] = sub_record
            parent_record.sub_delegations.append({
                "delegation_id": sub_del_id,
                "target_agent": target_id,
            })

            if router and router.routes:
                tasks_coro.append(self._invoke_sub_task(
                    sub_del_id, target_id, task, envelope, router, payload
                ))
            else:
                sub_record.status = "completed"
                sub_record.result = task
                sub_record.completed_at = time.time()
                sub_results.append({
                    "delegation_id": sub_del_id,
                    "target_agent": target_id,
                    "result": task,
                    "status": "completed",
                })
                target = self.registry.get(target_id)
                if target:
                    target.current_tasks = max(0, target.current_tasks - 1)

        # Run concurrent sub-tasks
        if tasks_coro:
            sub_results = await asyncio.gather(*tasks_coro)
            sub_results = list(sub_results)

        # Aggregate results
        all_completed = all(r.get("status") == "completed" for r in sub_results)
        combined_result = json.dumps(sub_results, ensure_ascii=False) if sub_results else "[]"

        parent_record.status = "completed" if all_completed else "partial"
        parent_record.result = combined_result
        parent_record.completed_at = time.time()

        log_event(logger, "fanout.completed",
                  state=f"delegation_id={delegation_id},status={parent_record.status}")

        yield Envelope(
            version="v1",
            type=MessageType.AGENT_RESPONSE,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=envelope.seq,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "target_agents": target_agent_ids,
                "result": combined_result,
                "status": parent_record.status,
                "pattern": "fan-out",
                "sub_count": len(sub_results),
            },
        ).model_dump()

    async def _invoke_sub_task(
        self,
        sub_del_id: str,
        target_id: str,
        task: str,
        envelope: Envelope,
        router: ProviderRouter,
        payload: dict,
    ) -> dict:
        """Invoke a single sub-task for fan-out and return the result dict."""
        target = self.registry.get(target_id)
        sub_record = self.delegations.get(sub_del_id)

        try:
            provider_name, provider_adapter = router.select(
                session_id=envelope.session_id,
                model=target.capabilities[0] if target and target.capabilities else None,
            )
            chunks = []
            async for event in provider_adapter.invoke(
                prompt=task,
                model=payload.get("model", "mock-model"),
            ):
                if event.type == "chunk":
                    chunks.append(event.content or "")
                elif event.type == "end":
                    break
                elif event.type == "error":
                    if sub_record:
                        sub_record.status = "failed"
                        sub_record.error = event.error_msg or "Provider error"
                        sub_record.completed_at = time.time()
                    if target:
                        target.current_tasks = max(0, target.current_tasks - 1)
                    return {
                        "delegation_id": sub_del_id,
                        "target_agent": target_id,
                        "result": None,
                        "status": "failed",
                        "error": event.error_msg,
                    }

            result_text = "".join(chunks) if chunks else "completed"
            if sub_record:
                sub_record.status = "completed"
                sub_record.result = result_text
                sub_record.completed_at = time.time()

        except Exception as e:
            if sub_record:
                sub_record.status = "failed"
                sub_record.error = str(e)
                sub_record.completed_at = time.time()
            result_text = None

        if target:
            target.current_tasks = max(0, target.current_tasks - 1)

        return {
            "delegation_id": sub_del_id,
            "target_agent": target_id,
            "result": result_text,
            "status": sub_record.status if sub_record else "unknown",
        }

    def get_delegation(self, delegation_id: str) -> Optional[DelegationRecord]:
        return self.delegations.get(delegation_id)

    def list_delegations(self) -> list[DelegationRecord]:
        return list(self.delegations.values())