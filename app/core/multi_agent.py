"""A2A_min_v1 Multi-Agent manager: registry, delegation, and coordination."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

from app.adapters.router import ProviderRouter
from app.core.logger import log_event, setup_logger
from app.core.security import SecurityManager
from app.models.envelope import Envelope, MessageType

logger = setup_logger("multi_agent")


SUCCESS_STATUSES = {"completed", "compensated"}
TERMINAL_FAILURE_STATUSES = {"failed", "offline", "not_found"}


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
    pattern: str = "single"
    status: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    sub_delegations: list[dict] = field(default_factory=list)
    compensations: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    session_id: Optional[str] = None


@dataclass
class AgentExecutionResult:
    delegation_id: str
    target_agent: str
    task: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    compensated: bool = False
    compensation: Optional[dict[str, Any]] = None
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        data = {
            "delegation_id": self.delegation_id,
            "target_agent": self.target_agent,
            "task": self.task,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.compensated:
            data["compensated"] = True
            data["compensation"] = self.compensation
        return data


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

    def find_available(
        self,
        capability: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Optional[AgentProfile]:
        """Find an available agent matching capability and/or role with capacity."""
        candidates = list(self.agents.values())
        if capability:
            candidates = [a for a in candidates if capability in a.capabilities]
        if role:
            candidates = [a for a in candidates if role in a.roles]
        candidates = [
            a for a in candidates
            if a.status == "online" and a.current_tasks < a.max_concurrent_tasks
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda a: a.current_tasks)
        return candidates[0]


@dataclass
class MultiAgentManager:
    """Orchestrates agent registration, delegation, and coordination."""

    registry: AgentRegistry = field(default_factory=AgentRegistry)
    delegations: dict[str, DelegationRecord] = field(default_factory=dict)
    http_timeout: float = 30.0
    http_transport: Optional[httpx.AsyncBaseTransport] = None

    def register_agent(
        self,
        profile: AgentProfile,
        security: Optional[SecurityManager] = None,
    ) -> str:
        """Register an agent and optionally create its inbound gateway API key."""
        outbound_api_key = profile.api_key
        if security:
            local_api_key = security.register_agent(
                agent_id=profile.agent_id,
                roles=profile.roles,
            )
            if outbound_api_key is None:
                profile.api_key = local_api_key
        self.registry.register(profile)
        return profile.agent_id

    def deregister_agent(self, agent_id: str) -> bool:
        return self.registry.deregister(agent_id)

    def get_agent(self, agent_id: str) -> Optional[AgentProfile]:
        return self.registry.get(agent_id)

    def list_agents(self) -> list[AgentProfile]:
        return self.registry.list_agents()

    def get_delegation(self, delegation_id: str) -> Optional[DelegationRecord]:
        return self.delegations.get(delegation_id)

    def list_delegations(self) -> list[DelegationRecord]:
        return list(self.delegations.values())

    async def handle_delegate(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Process a single-agent AGENT_DELEGATE envelope."""
        payload = envelope.payload
        target_agent_id = payload.get("target_agent", "")
        task = payload.get("task", "")
        source_agent = payload.get("source_agent", envelope.session_id)

        target_error = self._validate_target(target_agent_id)
        if target_error:
            yield self._error_envelope(envelope, target_error["code"], target_error["message"])
            return

        delegation_id = f"del-{uuid.uuid4().hex[:12]}"
        record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=target_agent_id,
            task=task,
            pattern=payload.get("pattern", "single"),
            status="running",
            session_id=envelope.session_id,
        )
        self.delegations[delegation_id] = record
        log_event(logger, "delegate.created", state=f"delegation_id={delegation_id},target={target_agent_id}")

        result = await self._execute_agent_task(
            target_id=target_agent_id,
            task=task,
            envelope=envelope,
            router=router,
            payload=payload,
            parent_record=record,
            pattern="single",
            delegation_id=delegation_id,
        )

        record.status = result.status
        record.result = result.result
        record.error = result.error
        record.completed_at = time.time()
        if result.compensation:
            record.compensations.append(result.compensation)

        log_event(logger, "delegate.completed", state=f"delegation_id={delegation_id},status={record.status}")

        if result.status in TERMINAL_FAILURE_STATUSES and payload.get("return_errors", True):
            yield self._error_envelope(
                envelope,
                "DELEGATION_FAILED" if result.status != "not_found" else "AGENT_NOT_FOUND",
                result.error or "Delegation failed",
                {"delegation_id": delegation_id},
            )
            return

        yield self._agent_response(
            envelope=envelope,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "target_agent": target_agent_id,
                "result": result.result or "",
                "status": record.status,
                "pattern": record.pattern,
                "compensations": record.compensations,
            },
        )

    def handle_response(self, envelope: Envelope) -> Optional[DelegationRecord]:
        """Process an AGENT_RESPONSE envelope and update the delegation record."""
        payload = envelope.payload
        delegation_id = payload.get("delegation_id", "")
        record = self.delegations.get(delegation_id)

        if not record:
            log_event(logger, "response.unknown_delegation", state=f"delegation_id={delegation_id}")
            return None

        record.result = payload.get("result", record.result)
        record.status = payload.get("status", record.status)
        record.completed_at = time.time()

        target = self.registry.get(record.target_agent)
        if target:
            target.current_tasks = max(0, target.current_tasks - 1)

        log_event(logger, "response.received", state=f"delegation_id={delegation_id},status={record.status}")
        return record

    async def handle_fan_out(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Fan-out delegation: send one task to multiple agents concurrently."""
        payload = envelope.payload
        target_agent_ids = payload.get("target_agents", [])
        task = payload.get("task", "")
        source_agent = payload.get("source_agent", envelope.session_id)

        validation_error = self._validate_targets_for_parent(envelope, target_agent_ids)
        if validation_error:
            yield validation_error
            return

        delegation_id = f"fan-{uuid.uuid4().hex[:12]}"
        parent_record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=",".join(target_agent_ids),
            task=task,
            pattern="fan-out",
            status="running",
            session_id=envelope.session_id,
            metadata={"failure_policy": payload.get("failure_policy", "partial")},
        )
        self.delegations[delegation_id] = parent_record
        log_event(logger, "fanout.created", state=f"delegation_id={delegation_id},targets={len(target_agent_ids)}")

        results = await self._run_parallel_targets(
            target_agent_ids=target_agent_ids,
            task=task,
            envelope=envelope,
            router=router,
            payload=payload,
            parent_record=parent_record,
            pattern="fan-out",
        )
        result_dicts = [r.as_dict() for r in results]

        parent_record.status = self._parent_status(results)
        parent_record.result = json.dumps(result_dicts, ensure_ascii=False)
        parent_record.completed_at = time.time()

        log_event(logger, "fanout.completed", state=f"delegation_id={delegation_id},status={parent_record.status}")

        yield self._agent_response(
            envelope=envelope,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "target_agents": target_agent_ids,
                "result": parent_record.result,
                "status": parent_record.status,
                "pattern": "fan-out",
                "sub_count": len(results),
                "sub_results": result_dicts,
                "compensations": parent_record.compensations,
            },
        )

    async def handle_fan_in(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Fan-in delegation: run multiple agents and aggregate into one result."""
        payload = envelope.payload
        target_agent_ids = payload.get("target_agents", [])
        task = payload.get("task", "")
        source_agent = payload.get("source_agent", envelope.session_id)

        validation_error = self._validate_targets_for_parent(envelope, target_agent_ids)
        if validation_error:
            yield validation_error
            return

        delegation_id = f"fin-{uuid.uuid4().hex[:12]}"
        parent_record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=",".join(target_agent_ids),
            task=task,
            pattern="fan-in",
            status="running",
            session_id=envelope.session_id,
            metadata={
                "aggregation": payload.get("aggregation", payload.get("aggregation_strategy", "json")),
                "failure_policy": payload.get("failure_policy", "partial"),
            },
        )
        self.delegations[delegation_id] = parent_record
        log_event(logger, "fanin.created", state=f"delegation_id={delegation_id},targets={len(target_agent_ids)}")

        results = await self._run_parallel_targets(
            target_agent_ids=target_agent_ids,
            task=task,
            envelope=envelope,
            router=router,
            payload=payload,
            parent_record=parent_record,
            pattern="fan-in",
        )
        aggregated = await self._aggregate_results(results, envelope, router, payload, parent_record)

        parent_record.status = self._parent_status(results)
        parent_record.result = aggregated
        parent_record.completed_at = time.time()

        log_event(logger, "fanin.completed", state=f"delegation_id={delegation_id},status={parent_record.status}")

        yield self._agent_response(
            envelope=envelope,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "target_agents": target_agent_ids,
                "result": aggregated,
                "status": parent_record.status,
                "pattern": "fan-in",
                "aggregation": parent_record.metadata.get("aggregation"),
                "sub_count": len(results),
                "sub_results": [r.as_dict() for r in results],
                "compensations": parent_record.compensations,
            },
        )

    async def handle_pipeline(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Pipeline delegation: run ordered agent steps with previous-result context."""
        payload = envelope.payload
        source_agent = payload.get("source_agent", envelope.session_id)
        base_task = payload.get("task", "")
        steps = self._normalize_pipeline_steps(payload)
        if not steps:
            yield self._error_envelope(envelope, "BAD_REQUEST", "pipeline requires steps or target_agents")
            return

        validation_error = self._validate_step_agents(envelope, steps)
        if validation_error:
            yield validation_error
            return

        delegation_id = f"pipe-{uuid.uuid4().hex[:12]}"
        parent_record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=",".join(str(step["agent"]) for step in steps),
            task=base_task,
            pattern="pipeline",
            status="running",
            session_id=envelope.session_id,
            metadata={"failure_policy": payload.get("failure_policy", "fail_fast")},
        )
        self.delegations[delegation_id] = parent_record
        log_event(logger, "pipeline.created", state=f"delegation_id={delegation_id},steps={len(steps)}")

        previous = payload.get("initial_context", base_task)
        results: list[AgentExecutionResult] = []
        failure_policy = payload.get("failure_policy", "fail_fast")

        for index, step in enumerate(steps, start=1):
            target_id = str(step["agent"])
            template = str(step.get("task") or "{previous}")
            step_task = self._render_template(
                template,
                base_task=base_task,
                previous=previous,
                step_index=index,
                agent_id=target_id,
            )
            result = await self._execute_agent_task(
                target_id=target_id,
                task=step_task,
                envelope=envelope,
                router=router,
                payload={**payload, **step},
                parent_record=parent_record,
                pattern="pipeline",
            )
            results.append(result)

            if result.status in SUCCESS_STATUSES:
                previous = result.result or ""
                continue

            previous = f"[{target_id} failed: {result.error or 'unknown error'}]"
            if failure_policy == "fail_fast":
                break

        parent_record.status = self._parent_status(results, fail_fast=failure_policy == "fail_fast")
        parent_record.result = previous
        parent_record.completed_at = time.time()

        log_event(logger, "pipeline.completed", state=f"delegation_id={delegation_id},status={parent_record.status}")

        yield self._agent_response(
            envelope=envelope,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "result": parent_record.result or "",
                "status": parent_record.status,
                "pattern": "pipeline",
                "steps": [r.as_dict() for r in results],
                "step_count": len(results),
                "compensations": parent_record.compensations,
            },
        )

    async def handle_planner_worker_reviewer(
        self,
        envelope: Envelope,
        router: Optional[ProviderRouter] = None,
    ) -> AsyncIterator[dict]:
        """Planner-worker-reviewer built-in collaboration flow."""
        payload = envelope.payload
        source_agent = payload.get("source_agent", envelope.session_id)
        base_task = payload.get("task", "")

        planner_id = payload.get("planner_agent") or self._first_agent_by_role("planner")
        reviewer_id = payload.get("reviewer_agent") or self._first_agent_by_role("reviewer")
        worker_ids = payload.get("worker_agents") or [a.agent_id for a in self.registry.find_by_role("worker")]

        missing_roles = []
        if not planner_id:
            missing_roles.append("planner")
        if not worker_ids:
            missing_roles.append("worker")
        if not reviewer_id:
            missing_roles.append("reviewer")
        if missing_roles:
            yield self._error_envelope(
                envelope,
                "AGENT_NOT_FOUND",
                f"planner-worker-reviewer missing roles: {missing_roles}",
            )
            return

        target_ids = [str(planner_id), *[str(w) for w in worker_ids], str(reviewer_id)]
        validation_error = self._validate_targets_for_parent(envelope, target_ids)
        if validation_error:
            yield validation_error
            return

        delegation_id = f"pwr-{uuid.uuid4().hex[:12]}"
        parent_record = DelegationRecord(
            delegation_id=delegation_id,
            source_agent=source_agent,
            target_agent=",".join(target_ids),
            task=base_task,
            pattern="planner-worker-reviewer",
            status="running",
            session_id=envelope.session_id,
            metadata={
                "aggregation": payload.get("aggregation", "summary"),
                "failure_policy": payload.get("failure_policy", "partial"),
            },
        )
        self.delegations[delegation_id] = parent_record
        log_event(logger, "pwr.created", state=f"delegation_id={delegation_id},workers={len(worker_ids)}")

        planner_task = payload.get("planner_task") or "Create an execution plan for: {input}"
        planner_result = await self._execute_agent_task(
            target_id=str(planner_id),
            task=self._render_template(planner_task, base_task=base_task, previous=base_task, agent_id=str(planner_id)),
            envelope=envelope,
            router=router,
            payload=payload,
            parent_record=parent_record,
            pattern="planner",
        )

        if planner_result.status not in SUCCESS_STATUSES and payload.get("failure_policy") == "fail_fast":
            parent_record.status = "failed"
            parent_record.error = planner_result.error
            parent_record.completed_at = time.time()
            yield self._agent_response(
                envelope,
                {
                    "delegation_id": delegation_id,
                    "source_agent": source_agent,
                    "result": "",
                    "status": parent_record.status,
                    "pattern": "planner-worker-reviewer",
                    "plan": planner_result.as_dict(),
                    "worker_results": [],
                    "review": None,
                    "compensations": parent_record.compensations,
                },
            )
            return

        plan_text = planner_result.result or base_task
        worker_task_template = payload.get("worker_task") or (
            "Execute the original task using this plan.\nOriginal task: {input}\nPlan: {previous}"
        )
        worker_payload = {**payload, "task": base_task}
        worker_results = await asyncio.gather(*[
            self._execute_agent_task(
                target_id=str(worker_id),
                task=self._render_template(
                    worker_task_template,
                    base_task=base_task,
                    previous=plan_text,
                    agent_id=str(worker_id),
                ),
                envelope=envelope,
                router=router,
                payload=worker_payload,
                parent_record=parent_record,
                pattern="worker",
            )
            for worker_id in worker_ids
        ])
        worker_aggregate = await self._aggregate_results(worker_results, envelope, router, payload, parent_record)

        reviewer_task = payload.get("reviewer_task") or (
            "Review the worker outputs against the plan.\nOriginal task: {input}\nPlan: {plan}\nWorker outputs: {work}"
        )
        review_prompt = self._render_template(
            reviewer_task,
            base_task=base_task,
            previous=worker_aggregate,
            agent_id=str(reviewer_id),
            extra={"plan": plan_text, "work": worker_aggregate},
        )
        reviewer_result = await self._execute_agent_task(
            target_id=str(reviewer_id),
            task=review_prompt,
            envelope=envelope,
            router=router,
            payload=payload,
            parent_record=parent_record,
            pattern="reviewer",
        )

        all_results = [planner_result, *worker_results, reviewer_result]
        parent_record.status = self._parent_status(all_results)
        final_payload = {
            "plan": planner_result.as_dict(),
            "worker_results": [r.as_dict() for r in worker_results],
            "review": reviewer_result.as_dict(),
            "worker_aggregate": worker_aggregate,
        }
        parent_record.result = json.dumps(final_payload, ensure_ascii=False)
        parent_record.completed_at = time.time()

        log_event(logger, "pwr.completed", state=f"delegation_id={delegation_id},status={parent_record.status}")

        yield self._agent_response(
            envelope=envelope,
            payload={
                "delegation_id": delegation_id,
                "source_agent": source_agent,
                "result": parent_record.result,
                "status": parent_record.status,
                "pattern": "planner-worker-reviewer",
                "plan": planner_result.as_dict(),
                "worker_results": [r.as_dict() for r in worker_results],
                "review": reviewer_result.as_dict(),
                "compensations": parent_record.compensations,
            },
        )

    async def _run_parallel_targets(
        self,
        target_agent_ids: list[str],
        task: str,
        envelope: Envelope,
        router: Optional[ProviderRouter],
        payload: dict[str, Any],
        parent_record: DelegationRecord,
        pattern: str,
    ) -> list[AgentExecutionResult]:
        tasks = []
        for index, target_id in enumerate(target_agent_ids):
            target_task = self._task_for_target(payload, target_id, index, task)
            tasks.append(self._execute_agent_task(
                target_id=target_id,
                task=target_task,
                envelope=envelope,
                router=router,
                payload=payload,
                parent_record=parent_record,
                pattern=pattern,
            ))
        return list(await asyncio.gather(*tasks))

    async def _execute_agent_task(
        self,
        target_id: str,
        task: str,
        envelope: Envelope,
        router: Optional[ProviderRouter],
        payload: dict[str, Any],
        parent_record: DelegationRecord,
        pattern: str,
        delegation_id: Optional[str] = None,
    ) -> AgentExecutionResult:
        start = time.time()
        sub_del_id = delegation_id or f"sub-{uuid.uuid4().hex[:8]}"
        source_agent = payload.get("source_agent", envelope.session_id)
        target = self.registry.get(target_id)

        if not target:
            return AgentExecutionResult(
                delegation_id=sub_del_id,
                target_agent=target_id,
                task=task,
                status="not_found",
                error=f"Agent '{target_id}' not found in registry",
            )
        if target.status != "online":
            return AgentExecutionResult(
                delegation_id=sub_del_id,
                target_agent=target_id,
                task=task,
                status="offline",
                error=f"Agent '{target_id}' is offline (status={target.status})",
            )
        if target.current_tasks >= target.max_concurrent_tasks:
            return AgentExecutionResult(
                delegation_id=sub_del_id,
                target_agent=target_id,
                task=task,
                status="failed",
                error=f"Agent '{target_id}' has no available capacity",
            )

        sub_record = self.delegations.get(sub_del_id)
        if sub_record is None:
            sub_record = DelegationRecord(
                delegation_id=sub_del_id,
                source_agent=source_agent,
                target_agent=target_id,
                task=task,
                pattern=pattern,
                status="running",
                session_id=envelope.session_id,
            )
            self.delegations[sub_del_id] = sub_record
        parent_record.sub_delegations.append({
            "delegation_id": sub_del_id,
            "target_agent": target_id,
            "pattern": pattern,
        })

        target.current_tasks += 1
        try:
            if target.endpoint:
                result_text = await self._invoke_http_agent(target, task, envelope, payload, sub_del_id)
            elif router and router.routes:
                result_text = await self._invoke_provider_agent(target, task, envelope, router, payload)
            else:
                result_text = task

            status = "completed"
            error = None
            compensated = False
            compensation = None
        except Exception as exc:
            result_text = None
            status = "failed"
            error = str(exc)
            compensation = await self._compensate_failure(
                failed_agent=target_id,
                failed_task=task,
                error=error,
                envelope=envelope,
                router=router,
                payload=payload,
                parent_record=parent_record,
            )
            compensated = compensation is not None
            if compensation:
                result_text = str(compensation.get("result", ""))
                status = "compensated"

        target.current_tasks = max(0, target.current_tasks - 1)
        duration_ms = (time.time() - start) * 1000

        sub_record.status = status
        sub_record.result = result_text
        sub_record.error = error
        sub_record.completed_at = time.time()
        if compensation:
            sub_record.compensations.append(compensation)

        return AgentExecutionResult(
            delegation_id=sub_del_id,
            target_agent=target_id,
            task=task,
            status=status,
            result=result_text,
            error=error,
            compensated=compensated,
            compensation=compensation,
            duration_ms=duration_ms,
        )

    async def _invoke_provider_agent(
        self,
        target: AgentProfile,
        task: str,
        envelope: Envelope,
        router: ProviderRouter,
        payload: dict[str, Any],
    ) -> str:
        provider_name, provider_adapter = router.select(
            session_id=envelope.session_id,
            model=target.capabilities[0] if target.capabilities else None,
        )
        chunks: list[str] = []
        async for event in provider_adapter.invoke(
            prompt=task,
            model=payload.get("model", "mock-model"),
        ):
            if event.type == "chunk":
                chunks.append(event.content or "")
            elif event.type == "end":
                break
            elif event.type == "error":
                raise RuntimeError(event.error_msg or f"Provider '{provider_name}' returned an error")
        return "".join(chunks) if chunks else "completed"

    async def _invoke_http_agent(
        self,
        target: AgentProfile,
        task: str,
        envelope: Envelope,
        payload: dict[str, Any],
        delegation_id: str,
    ) -> str:
        if not target.endpoint:
            raise RuntimeError(f"Agent '{target.agent_id}' has no endpoint")

        agent_api_keys = payload.get("agent_api_keys") or {}
        api_key = agent_api_keys.get(target.agent_id, target.api_key)
        headers = {
            "Content-Type": "application/json",
            "X-Agent-ID": payload.get("source_agent", envelope.session_id),
        }
        if api_key:
            headers["X-API-Key"] = api_key

        body = Envelope(
            type=MessageType.INVOKE,
            session_id=envelope.session_id,
            corr_id=delegation_id,
            payload={
                "prompt": task,
                "model": payload.get("model", "mock-model"),
                "task_type": payload.get("task_type", "multi_agent"),
            },
        ).model_dump(mode="json")

        timeout = float(payload.get("http_timeout", self.http_timeout))
        async with httpx.AsyncClient(timeout=timeout, transport=self.http_transport) as client:
            response = await client.post(target.endpoint, json=body, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP agent '{target.agent_id}' returned {response.status_code}: {response.text}")
            data = response.json()
        return self._extract_http_result(data)

    def _extract_http_result(self, data: Any) -> str:
        if isinstance(data, list):
            return "\n".join(self._extract_http_result(item) for item in data)
        if not isinstance(data, dict):
            return str(data)

        if "error" in data:
            error = data.get("error")
            if isinstance(error, dict):
                raise RuntimeError(error.get("message") or error.get("code") or "HTTP agent returned error")
            raise RuntimeError(str(error))

        if "result" in data:
            return str(data["result"])

        if "task" in data:
            task_text = self._extract_task_result(data["task"])
            if task_text:
                return task_text
            return json.dumps(data["task"], ensure_ascii=False)

        envelopes = data.get("chunks")
        if envelopes is None and "type" in data:
            envelopes = [data]
        if isinstance(envelopes, list):
            chunks: list[str] = []
            for item in envelopes:
                if not isinstance(item, dict):
                    continue
                msg_type = self._message_type_value(item.get("type"))
                payload = item.get("payload", {})
                if msg_type == MessageType.ERROR.value:
                    raise RuntimeError(payload.get("message") or payload.get("error_code") or "HTTP agent error")
                if msg_type == MessageType.STREAM_CHUNK.value:
                    chunks.append(str(payload.get("content", "")))
            if chunks:
                return "".join(chunks)

        return json.dumps(data, ensure_ascii=False)

    def _extract_task_result(self, task: Any) -> str:
        if not isinstance(task, dict):
            return ""
        texts: list[str] = []
        for artifact in task.get("artifacts", []) or []:
            if not isinstance(artifact, dict):
                continue
            for part in artifact.get("parts", []) or []:
                if isinstance(part, dict) and part.get("text") is not None:
                    texts.append(str(part["text"]))
        return "".join(texts)

    async def _aggregate_results(
        self,
        results: list[AgentExecutionResult],
        envelope: Envelope,
        router: Optional[ProviderRouter],
        payload: dict[str, Any],
        parent_record: DelegationRecord,
    ) -> str:
        mode = payload.get("aggregation", payload.get("aggregation_strategy", "json"))
        result_dicts = [r.as_dict() for r in results]

        if mode == "concat":
            return "\n".join(
                f"[{r.target_agent}] {r.result}"
                for r in results
                if r.status in SUCCESS_STATUSES and r.result is not None
            )

        if mode == "summary":
            aggregator_agent = payload.get("aggregator_agent")
            successful = [r for r in results if r.status in SUCCESS_STATUSES]
            failed = [r for r in results if r.status not in SUCCESS_STATUSES]
            summary_seed = json.dumps(result_dicts, ensure_ascii=False)
            if aggregator_agent:
                aggregation_task = (
                    payload.get("aggregation_task")
                    or "Aggregate these multi-agent results into a concise final answer:\n{previous}"
                )
                rendered = self._render_template(
                    aggregation_task,
                    base_task=payload.get("task", ""),
                    previous=summary_seed,
                    agent_id=str(aggregator_agent),
                )
                agg_result = await self._execute_agent_task(
                    target_id=str(aggregator_agent),
                    task=rendered,
                    envelope=envelope,
                    router=router,
                    payload={**payload, "failure_policy": "partial"},
                    parent_record=parent_record,
                    pattern="aggregation",
                )
                if agg_result.status in SUCCESS_STATUSES and agg_result.result:
                    return agg_result.result
            return json.dumps({
                "summary": f"{len(successful)} successful, {len(failed)} failed",
                "successful_agents": [r.target_agent for r in successful],
                "failed_agents": [r.target_agent for r in failed],
                "items": result_dicts,
            }, ensure_ascii=False)

        return json.dumps(result_dicts, ensure_ascii=False)

    async def _compensate_failure(
        self,
        failed_agent: str,
        failed_task: str,
        error: str,
        envelope: Envelope,
        router: Optional[ProviderRouter],
        payload: dict[str, Any],
        parent_record: DelegationRecord,
    ) -> Optional[dict[str, Any]]:
        if payload.get("failure_policy") != "compensate" and not payload.get("compensate_failures"):
            return None

        compensation_config = payload.get("compensation") or {}
        compensation_agent = (
            payload.get("compensation_agent")
            or compensation_config.get("agent")
            or compensation_config.get("target_agent")
        )
        fallback_result = payload.get("fallback_result", compensation_config.get("fallback_result"))

        if compensation_agent:
            template = compensation_config.get("task") or payload.get("compensation_task") or (
                "Compensate failed task.\nFailed agent: {failed_agent}\n"
                "Error: {error}\nTask: {failed_task}"
            )
            compensation_task = self._render_template(
                template,
                base_task=failed_task,
                previous=error,
                agent_id=str(compensation_agent),
                extra={
                    "failed_agent": failed_agent,
                    "failed_task": failed_task,
                    "error": error,
                },
            )
            result = await self._execute_agent_task(
                target_id=str(compensation_agent),
                task=compensation_task,
                envelope=envelope,
                router=router,
                payload={**payload, "failure_policy": "partial", "compensate_failures": False},
                parent_record=parent_record,
                pattern="compensation",
            )
            if result.status in SUCCESS_STATUSES:
                compensation = {
                    "failed_agent": failed_agent,
                    "compensation_agent": str(compensation_agent),
                    "status": result.status,
                    "result": result.result,
                    "error": error,
                }
                parent_record.compensations.append(compensation)
                return compensation

        if fallback_result is not None:
            compensation = {
                "failed_agent": failed_agent,
                "compensation_agent": None,
                "status": "fallback",
                "result": str(fallback_result),
                "error": error,
            }
            parent_record.compensations.append(compensation)
            return compensation

        return None

    def _validate_target(self, target_id: str) -> Optional[dict[str, str]]:
        target = self.registry.get(target_id)
        if not target:
            log_event(logger, "delegate.agent_not_found", error_code="AGENT_NOT_FOUND", state=f"target={target_id}")
            return {
                "code": "AGENT_NOT_FOUND",
                "message": f"Agent '{target_id}' not found in registry",
            }
        if target.status != "online":
            log_event(
                logger,
                "delegate.agent_offline",
                error_code="DELEGATION_FAILED",
                state=f"target={target_id},status={target.status}",
            )
            return {
                "code": "DELEGATION_FAILED",
                "message": f"Agent '{target_id}' is offline (status={target.status})",
            }
        return None

    def _validate_targets_for_parent(self, envelope: Envelope, target_agent_ids: list[str]) -> Optional[dict]:
        if not target_agent_ids:
            return self._error_envelope(envelope, "BAD_REQUEST", "target_agents list is empty")
        missing = [aid for aid in target_agent_ids if not self.registry.get(aid)]
        if missing:
            return self._error_envelope(envelope, "AGENT_NOT_FOUND", f"Agents not found: {missing}")
        offline = [
            aid for aid in target_agent_ids
            if self.registry.get(aid) and self.registry.get(aid).status != "online"
        ]
        if offline:
            return self._error_envelope(envelope, "DELEGATION_FAILED", f"Agents offline: {offline}")
        return None

    def _validate_step_agents(self, envelope: Envelope, steps: list[dict[str, Any]]) -> Optional[dict]:
        target_ids = [str(step.get("agent") or step.get("target_agent") or "") for step in steps]
        return self._validate_targets_for_parent(envelope, target_ids)

    def _normalize_pipeline_steps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        steps = payload.get("steps")
        if isinstance(steps, list) and steps:
            normalized = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                agent = step.get("agent") or step.get("target_agent")
                if agent:
                    normalized.append({**step, "agent": agent})
            return normalized
        target_agents = payload.get("target_agents") or []
        return [{"agent": agent, "task": "{previous}"} for agent in target_agents]

    def _task_for_target(self, payload: dict[str, Any], target_id: str, index: int, default_task: str) -> str:
        tasks = payload.get("tasks")
        if isinstance(tasks, dict) and target_id in tasks:
            return str(tasks[target_id])
        if isinstance(tasks, list) and index < len(tasks):
            return str(tasks[index])
        task_template = payload.get("task_template")
        if task_template:
            return self._render_template(
                str(task_template),
                base_task=default_task,
                previous=default_task,
                step_index=index + 1,
                agent_id=target_id,
            )
        return default_task

    def _render_template(
        self,
        template: str,
        base_task: str,
        previous: str,
        step_index: int = 1,
        agent_id: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> str:
        values = {
            "input": base_task,
            "task": base_task,
            "previous": previous,
            "result": previous,
            "step_index": step_index,
            "agent_id": agent_id,
        }
        if extra:
            values.update(extra)
        try:
            return template.format(**values)
        except Exception:
            return f"{template}\n\nInput: {base_task}\nPrevious: {previous}"

    def _first_agent_by_role(self, role: str) -> Optional[str]:
        agents = self.registry.find_by_role(role)
        if not agents:
            return None
        return agents[0].agent_id

    def _parent_status(
        self,
        results: list[AgentExecutionResult],
        fail_fast: bool = False,
    ) -> str:
        if not results:
            return "failed"
        if all(r.status == "completed" for r in results):
            return "completed"
        if any(r.status == "compensated" for r in results):
            uncompensated_failures = [r for r in results if r.status not in SUCCESS_STATUSES]
            return "partial" if uncompensated_failures else "compensated"
        if fail_fast and any(r.status in TERMINAL_FAILURE_STATUSES for r in results):
            return "failed"
        if any(r.status in TERMINAL_FAILURE_STATUSES for r in results):
            return "partial"
        return "completed"

    def _message_type_value(self, value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    def _error_envelope(
        self,
        envelope: Envelope,
        error_code: str,
        message: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict:
        payload = {"error_code": error_code, "message": message}
        if extra:
            payload.update(extra)
        return Envelope(
            version="v1",
            type=MessageType.ERROR,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=envelope.seq,
            payload=payload,
        ).model_dump()

    def _agent_response(self, envelope: Envelope, payload: dict[str, Any]) -> dict:
        return Envelope(
            version="v1",
            type=MessageType.AGENT_RESPONSE,
            session_id=envelope.session_id,
            corr_id=envelope.corr_id,
            seq=envelope.seq,
            payload=payload,
        ).model_dump()
