"""A2A_min_v1 Gateway Service — FastAPI-based gateway with full A2A protocol support."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import GatewayConfig, load_config, validate_config
from app.core.errors import (
    AUTH_FAILED, ALREADY_CANCELLED, BAD_REQUEST, CANCELLED, CONFIG_ERROR, DUPLICATE_INVOKE,
    EMPTY_REQUEST, FIRST_TOKEN_TIMEOUT, INVALID_MESSAGE_TYPE, INVALID_PAYLOAD,
    INVALID_VERSION, MSG_AFTER_TERMINAL, PROVIDER_ERROR, PROVIDER_RESPONSE_TIMEOUT,
    QUEUE_FULL, RATE_LIMITED, SEQ_DUPLICATE, SEQ_GAP, SEQ_ROLLBACK,
    TOTAL_TASK_TIMEOUT, TOKEN_INTERVAL_TIMEOUT, UNKNOWN_SESSION,
    AGENT_NOT_FOUND, DELEGATION_FAILED,
    get_error_def,
)
from app.core.flow_control import BoundedQueue, RateLimiter
from app.core.idempotency import IdempotencyManager, IdempotencyAction
from app.core.logger import setup_logger, log_event
from app.core.metrics import Metrics, get_metrics
from app.core.seq_checker import SeqChecker, SeqViolationKind
from app.core.state_machine import EventType, GatewayStateMachine
from app.core.tracing import SpanOperation, TraceCollector, TraceContext
from app.core.security import SecurityConfig, SecurityManager
from app.core.policy_filter import FilterConfig, PolicyFilter
from app.core.audit import AuditEntry, AuditLogger
from app.core.retry import RetryConfig, RetryManager
from app.core.timeout import TimeoutChecker
from app.models.envelope import (
    Envelope, MessageType, ProtocolVersion, LEGACY_MESSAGE_MAP,
    make_envelope, make_error_envelope,
)
from app.models.state import SessionState
from app.adapters.provider import ProviderAdapter, ProviderConfig, ProviderType
from app.adapters.mock_provider import MockProviderAdapter, MockScenario
from app.adapters.router import ProviderRouter
from app.core.multi_agent import AgentProfile, MultiAgentManager

logger = setup_logger("gateway")


# ---------------------------------------------------------------------------
# Gateway Session Store
# ---------------------------------------------------------------------------
class SessionStore:
    """Manages all active sessions, their state machines, timers, and queues."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.sessions: dict[str, GatewayStateMachine] = {}
        self.queues: dict[str, BoundedQueue] = {}
        self.idempotency = IdempotencyManager()
        self.seq_checker = SeqChecker()
        self.timeout_checker = TimeoutChecker(
            first_token_timeout=config.first_token_timeout,
            token_interval_timeout=config.token_interval_timeout,
            total_task_timeout=config.total_task_timeout,
            provider_response_timeout=config.provider_response_timeout,
        )
        self.trace_collector = TraceCollector()
        self.audit = AuditLogger(log_dir=config.audit_log_dir) if config.audit_enabled else None
        self.last_seen: dict[str, float] = {}  # session_id -> last heartbeat time

    def get_or_create(self, session_id: str, corr_id: str) -> GatewayStateMachine:
        if session_id not in self.sessions:
            sm = GatewayStateMachine(session_id=session_id)
            self.sessions[session_id] = sm
            self.queues[session_id] = BoundedQueue(max_length=self.config.max_queue_length)
        return self.sessions[session_id]

    def get(self, session_id: str) -> Optional[GatewayStateMachine]:
        return self.sessions.get(session_id)

    def get_queue(self, session_id: str) -> Optional[BoundedQueue]:
        return self.queues.get(session_id)

    def remove(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.queues.pop(session_id, None)
        self.last_seen.pop(session_id, None)
        self.timeout_checker.remove(session_id)


# ---------------------------------------------------------------------------
# Gateway Application
# ---------------------------------------------------------------------------
class GatewayApp:
    """Main Gateway application wiring together all components."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.session_store = SessionStore(config)
        self.security = SecurityManager(SecurityConfig(
            enabled=config.security_enabled,
            require_agent_id=config.require_agent_id,
            max_input_length=config.max_input_length,
            max_output_length=config.max_output_length,
        ))
        self.policy_filter = PolicyFilter(FilterConfig(
            max_input_chars=config.max_input_length,
            max_output_chars=config.max_output_length,
        ))
        self.rate_limiter = RateLimiter(max_tokens=config.send_rate_limit)
        self.retry_manager = RetryManager(RetryConfig(
            max_retries=config.max_retries,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
            backoff_factor=config.retry_backoff_factor,
        ))
        self.router = ProviderRouter(strategy=config.strategy)
        self.multi_agent = MultiAgentManager()
        self._setup_providers()

    def _setup_providers(self) -> None:
        """Initialize provider adapters from configuration."""
        from app.adapters.openai_provider import OpenAIProviderAdapter
        from app.adapters.ollama_provider import OllamaProviderAdapter

        for pe in self.config.providers:
            ptype = ProviderType(pe.provider_type)
            pconfig = ProviderConfig(
                provider_type=ptype,
                name=pe.name,
                base_url=pe.endpoint,
                model=pe.model,
                api_key=pe.api_key,
                timeout=pe.timeout,
                max_tokens=pe.max_tokens,
                temperature=pe.temperature,
            )

            if ptype == ProviderType.OPENAI_COMPATIBLE:
                adapter: ProviderAdapter = OpenAIProviderAdapter(pconfig)
            elif ptype == ProviderType.OLLAMA:
                adapter = OllamaProviderAdapter(pconfig)
            elif ptype == ProviderType.ANTHROPIC_COMPATIBLE:
                try:
                    from app.adapters.anthropic_provider import AnthropicProviderAdapter
                    adapter = AnthropicProviderAdapter(pconfig)
                except ImportError:
                    logger.warning(f"Skipping Anthropic provider '{pe.name}': anthropic package not installed")
                    continue
            elif ptype == ProviderType.MOCK:
                adapter = MockProviderAdapter()
            else:
                logger.warning(f"Unknown provider type: {pe.provider_type}")
                continue

            self.router.add_route(
                name=pe.name,
                adapter=adapter,
                capabilities=pe.capabilities,
                models=[pe.model],
                task_types=pe.task_types,
            )
            log_event(logger, "gateway.provider_registered", state=pe.name)

        if not self.router.routes:
            # Add a mock provider as fallback
            mock = MockProviderAdapter()
            self.router.add_route(name="default_mock", adapter=mock)
            log_event(logger, "gateway.mock_fallback")

    async def handle_invoke(self, envelope: Envelope, agent_id: Optional[str] = None,
                            api_key: Optional[str] = None) -> AsyncIterator[dict]:
        """Handle an INVOKE message: validate -> route -> stream -> end."""
        session_id = envelope.session_id
        corr_id = envelope.corr_id
        payload = envelope.payload
        seq = 0

        # --- Security checks ---
        if self.config.security_enabled:
            if not self.security.validate_api_key(api_key):
                yield make_error_envelope(session_id, corr_id, AUTH_FAILED.code,
                                          AUTH_FAILED.description).model_dump()
                return
            if not self.security.validate_agent_id(agent_id):
                yield make_error_envelope(session_id, corr_id, AUTH_FAILED.code,
                                          "Agent identity required").model_dump()
                return

        # --- Input policy filter ---
        filter_result = self.policy_filter.filter_input(payload)
        if not filter_result.passed:
            yield make_error_envelope(session_id, corr_id, filter_result.error_code or "BAD_REQUEST",
                                      filter_result.reason).model_dump()
            return

        # --- Idempotency check ---
        action, cached = self.session_store.idempotency.check_invoke(corr_id)
        if action == IdempotencyAction.REJECT:
            yield make_error_envelope(session_id, corr_id, DUPLICATE_INVOKE.code,
                                      DUPLICATE_INVOKE.description).model_dump()
            return
        if action == IdempotencyAction.REUSE and cached and cached.response:
            yield cached.response
            return

        # --- Rate limit ---
        if not self.rate_limiter.acquire():
            yield make_error_envelope(session_id, corr_id, RATE_LIMITED.code,
                                      RATE_LIMITED.description).model_dump()
            return

        # --- Create/get session ---
        sm = self.session_store.get_or_create(session_id, corr_id)
        result = sm.on_event(EventType.INVOKE)
        if not result.accepted:
            yield make_error_envelope(session_id, corr_id, MSG_AFTER_TERMINAL.code,
                                      result.reason).model_dump()
            return

        # --- Register with idempotency manager ---
        self.session_store.idempotency.register(corr_id, "INVOKE", sm.state)

        # --- Start trace ---
        trace = TraceContext.new(operation=SpanOperation.AGENT_INVOKE.value)
        trace.attributes["session_id"] = session_id
        trace.attributes["corr_id"] = corr_id

        # --- Start timeout tracking ---
        self.session_store.timeout_checker.register(session_id, corr_id)

        # --- Audit ---
        if self.session_store.audit:
            self.session_store.audit.record(AuditEntry(
                session_id=session_id, corr_id=corr_id, event="INVOKE",
                model=payload.get("model"), request_summary={"prompt_length": len(payload.get("prompt", ""))},
                trace_id=trace.trace_id,
            ))

        # --- Route to provider ---
        model = payload.get("model", "")
        task_type = payload.get("task_type", "")
        try:
            provider_name, provider = self.router.select(
                session_id=session_id, model=model, task_type=task_type
            )
        except RuntimeError:
            yield make_error_envelope(session_id, corr_id, CONFIG_ERROR.code,
                                      "No providers configured").model_dump()
            return

        # --- Stream from provider ---
        prompt = payload.get("prompt", "")
        messages = payload.get("messages")
        kwargs: dict[str, Any] = {"model": model}
        if messages:
            kwargs["messages"] = messages

        start_time = time.time()
        first_token_time: Optional[float] = None
        total_tokens = 0

        try:
            async for event in provider.invoke(prompt, **kwargs):
                # Check if cancelled
                if sm.state == SessionState.CANCELLED:
                    log_event(logger, "gateway.cancel_stopped_stream",
                              session_id=session_id, corr_id=corr_id)
                    break

                # Check terminal state
                if sm.state.is_terminal:
                    log_event(logger, "gateway.terminal_stopped_stream",
                              session_id=session_id, corr_id=corr_id)
                    break

                if event.type == "chunk":
                    seq += 1
                    total_tokens += 1
                    if first_token_time is None:
                        first_token_time = time.time()

                    # Update state to streaming on first chunk
                    if sm.state == SessionState.INVOKED:
                        sm.on_event(EventType.STREAM_CHUNK)

                    self.session_store.timeout_checker.on_chunk(session_id)

                    # Flow control: check queue
                    queue = self.session_store.get_queue(session_id)
                    if queue and queue.is_full:
                        log_event(logger, "gateway.queue_full_warning",
                                  session_id=session_id, corr_id=corr_id)

                    chunk_env = make_envelope(
                        MessageType.STREAM_CHUNK,
                        session_id,
                        corr_id,
                        {"content": event.content or ""},
                        seq=seq,
                    )
                    yield chunk_env.model_dump()

                    # Update idempotency state
                    self.session_store.idempotency.update_state(corr_id, sm.state)

                elif event.type == "end":
                    sm.on_event(EventType.STREAM_END)
                    end_env = make_envelope(
                        MessageType.STREAM_END,
                        session_id,
                        corr_id,
                        {"reason": event.finish_reason or "completed", "total_tokens": total_tokens},
                        seq=seq,
                    )
                    yield end_env.model_dump()

                    # Record metrics
                    metrics = get_metrics()
                    duration_ms = (time.time() - start_time) * 1000
                    first_token_latency = (first_token_time - start_time) * 1000 if first_token_time else None
                    metrics.record_success(first_token_latency=first_token_latency,
                                           total_duration=duration_ms)

                    # Audit
                    if self.session_store.audit:
                        self.session_store.audit.record(AuditEntry(
                            session_id=session_id, corr_id=corr_id, event="STREAM_END",
                            model=model, provider=provider_name,
                            duration_ms=duration_ms,
                            response_summary={"total_tokens": total_tokens},
                            trace_id=trace.trace_id,
                        ))

                    # Cleanup
                    self.session_store.seq_checker.reset(corr_id)
                    self.session_store.timeout_checker.remove(session_id)
                    trace.finish()

                    # Store response in idempotency cache (simplified — real impl would cache full response)
                    self.session_store.idempotency.update_state(corr_id, sm.state)

                    return

                elif event.type == "error":
                    sm.on_event(EventType.ERROR)
                    error_env = make_error_envelope(
                        session_id, corr_id,
                        event.error_code or PROVIDER_ERROR.code,
                        event.error_msg or PROVIDER_ERROR.description,
                        recoverable=get_error_def(event.error_code or "PROVIDER_ERROR").recoverable,
                        retry_recommended=get_error_def(event.error_code or "PROVIDER_ERROR").retry_recommended,
                        source="provider",
                        seq=seq,
                    )
                    yield error_env.model_dump()

                    metrics = get_metrics()
                    metrics.record_failure()

                    if self.session_store.audit:
                        self.session_store.audit.record(AuditEntry(
                            session_id=session_id, corr_id=corr_id, event="ERROR",
                            model=model, provider=provider_name,
                            error_code=event.error_code,
                            error_msg=event.error_msg,
                            duration_ms=(time.time() - start_time) * 1000,
                            trace_id=trace.trace_id,
                        ))

                    self.session_store.timeout_checker.remove(session_id)
                    self.session_store.idempotency.update_state(corr_id, sm.state)
                    trace.finish()
                    return

        except Exception as e:
            sm.on_event(EventType.ERROR)
            yield make_error_envelope(session_id, corr_id, PROVIDER_ERROR.code,
                                      str(e), source="provider").model_dump()
            get_metrics().record_failure()
            trace.finish()

    async def handle_cancel(self, envelope: Envelope) -> dict:
        """Handle a CANCEL message."""
        session_id = envelope.session_id
        corr_id = envelope.corr_id

        # Idempotency check — duplicate CANCEL on already-cancelled returns IGNORE
        action, _ = self.session_store.idempotency.check_cancel(corr_id)
        if action == IdempotencyAction.IGNORE:
            return make_error_envelope(session_id, corr_id, ALREADY_CANCELLED.code,
                                       ALREADY_CANCELLED.description).model_dump()

        sm = self.session_store.get(session_id)
        if sm is None:
            return make_error_envelope(session_id, corr_id, UNKNOWN_SESSION.code,
                                       UNKNOWN_SESSION.description).model_dump()

        result = sm.on_event(EventType.CANCEL)
        if not result.accepted:
            return make_error_envelope(session_id, corr_id, MSG_AFTER_TERMINAL.code,
                                       result.reason).model_dump()

        # Register idempotency so duplicate CANCEL is detected
        self.session_store.idempotency.register(corr_id, "CANCEL", sm.state)
        get_metrics().record_cancel()

        log_event(logger, "gateway.cancel", session_id=session_id, corr_id=corr_id)

        # Audit
        if self.session_store.audit:
            self.session_store.audit.record(AuditEntry(
                session_id=session_id, corr_id=corr_id, event="CANCEL",
                error_code=CANCELLED.code,
            ))

        return make_envelope(
            MessageType.ERROR,
            session_id,
            corr_id,
            {"error_code": "CANCELLED", "message": "任务已取消", "source": "gateway"},
            seq=envelope.seq,
        ).model_dump()

    async def handle_heartbeat(self, envelope: Envelope) -> dict:
        """Handle a HEARTBEAT message."""
        session_id = envelope.session_id
        corr_id = envelope.corr_id

        now = time.time()
        self.session_store.last_seen[session_id] = now

        sm = self.session_store.get(session_id)
        if sm is not None:
            sm.on_event(EventType.HEARTBEAT)
        else:
            # Register session on heartbeat even if not invoked yet
            self.session_store.get_or_create(session_id, corr_id)
            self.session_store.last_seen[session_id] = now

        self.session_store.timeout_checker.on_heartbeat(session_id)

        log_event(logger, "gateway.heartbeat", session_id=session_id, corr_id=corr_id)

        return make_envelope(
            MessageType.HEARTBEAT,
            session_id,
            corr_id,
            {"status": "alive", "last_seen": now},
        ).model_dump()

    async def handle_envelope(self, raw: dict, agent_id: Optional[str] = None,
                              api_key: Optional[str] = None) -> AsyncIterator[dict]:
        """Parse and route an incoming envelope."""
        # --- Schema validation ---
        try:
            envelope = Envelope(**raw)
        except Exception as e:
            error_msg = str(e)
            # Try to extract session_id and corr_id for the error response
            sid = raw.get("session_id", "unknown")
            cid = raw.get("corr_id", "unknown")
            yield make_error_envelope(sid, cid, BAD_REQUEST.code,
                                      f"Schema validation failed: {error_msg}").model_dump()
            return

        # --- Version check (#33) ---
        # Already handled by Pydantic validator in Envelope

        log_event(logger, "gateway.receive",
                  session_id=envelope.session_id,
                  corr_id=envelope.corr_id,
                  seq=envelope.seq,
                  msg_type=envelope.type.value)

        if envelope.type == MessageType.INVOKE:
            async for chunk in self.handle_invoke(envelope, agent_id=agent_id, api_key=api_key):
                yield chunk

        elif envelope.type == MessageType.CANCEL:
            result = await self.handle_cancel(envelope)
            yield result

        elif envelope.type == MessageType.HEARTBEAT:
            result = await self.handle_heartbeat(envelope)
            yield result

        elif envelope.type == MessageType.STREAM_CHUNK:
            # Incoming STREAM_CHUNK from provider side — validate seq
            if envelope.seq is not None:
                seq_result = self.session_store.seq_checker.check(envelope.corr_id, envelope.seq)
                if not seq_result.ok:
                    error_code = {
                        SeqViolationKind.DUPLICATE: SEQ_DUPLICATE.code,
                        SeqViolationKind.GAP: SEQ_GAP.code,
                        SeqViolationKind.ROLLBACK: SEQ_ROLLBACK.code,
                    }.get(seq_result.violation, "BAD_REQUEST") if seq_result.violation else "BAD_REQUEST"
                    yield make_error_envelope(envelope.session_id, envelope.corr_id,
                                              error_code, seq_result.reason).model_dump()
                    return

            # Check terminal state
            sm = self.session_store.get(envelope.session_id)
            if sm and sm.state.is_terminal:
                yield make_error_envelope(envelope.session_id, envelope.corr_id,
                                          MSG_AFTER_TERMINAL.code,
                                          MSG_AFTER_TERMINAL.description).model_dump()
                return

            yield envelope.model_dump()

        elif envelope.type == MessageType.STREAM_END:
            # Check terminal state
            sm = self.session_store.get(envelope.session_id)
            if sm and sm.state.is_terminal:
                action, _ = self.session_store.idempotency.check_stream_end(envelope.corr_id)
                if action == IdempotencyAction.IGNORE:
                    yield make_error_envelope(envelope.session_id, envelope.corr_id,
                                              MSG_AFTER_TERMINAL.code,
                                              "STREAM_END on terminal session").model_dump()
                    return

            yield envelope.model_dump()

        elif envelope.type == MessageType.ERROR:
            yield envelope.model_dump()

        elif envelope.type == MessageType.AGENT_DELEGATE:
            async for resp in self.multi_agent.handle_delegate(envelope, self.router):
                yield resp

        elif envelope.type == MessageType.AGENT_RESPONSE:
            record = self.multi_agent.handle_response(envelope)
            if record:
                yield make_envelope(
                    MessageType.HEARTBEAT,
                    envelope.session_id,
                    envelope.corr_id,
                    {"status": "response_recorded", "delegation_id": record.delegation_id},
                ).model_dump()
            else:
                yield make_error_envelope(
                    envelope.session_id, envelope.corr_id, UNKNOWN_SESSION.code,
                    "Delegation ID not found",
                ).model_dump()

        else:
            yield make_error_envelope(envelope.session_id, envelope.corr_id,
                                      INVALID_MESSAGE_TYPE.code,
                                      f"Unsupported message type: {envelope.type.value}").model_dump()


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    if config is None:
        config = load_config()

    errors = validate_config(config)
    if errors:
        for e in errors:
            logger.error(f"Config error: {e}")

    gateway = GatewayApp(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log_event(logger, "gateway.startup", state=f"port={config.port}")
        yield
        log_event(logger, "gateway.shutdown")

    app = FastAPI(title="A2A_min_v1 Gateway", version="1.0.0", lifespan=lifespan)

    # --- REST endpoint: /invoke ---
    @app.post("/invoke")
    async def invoke_endpoint(request: Request):
        """Synchronous invoke — returns full response (non-streaming)."""
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=make_error_envelope("unknown", "unknown", BAD_REQUEST.code,
                                            "Invalid JSON body").model_dump(),
            )

        api_key = request.headers.get("X-API-Key")
        agent_id = request.headers.get("X-Agent-ID")

        chunks = []
        async for chunk in gateway.handle_envelope(raw, agent_id=agent_id, api_key=api_key):
            chunks.append(chunk)

        if len(chunks) == 1:
            return JSONResponse(content=chunks[0])
        return JSONResponse(content={"chunks": chunks})

    # --- SSE endpoint: /stream ---
    @app.post("/stream")
    async def stream_endpoint(request: Request):
        """Streaming invoke — returns SSE stream of chunks."""
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=make_error_envelope("unknown", "unknown", BAD_REQUEST.code,
                                            "Invalid JSON body").model_dump(),
            )

        api_key = request.headers.get("X-API-Key")
        agent_id = request.headers.get("X-Agent-ID")

        async def event_generator():
            import json
            async for chunk in gateway.handle_envelope(raw, agent_id=agent_id, api_key=api_key):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # --- WebSocket endpoint: /ws ---
    @app.websocket("/ws")
    async def websocket_endpoint(websocket):
        """WebSocket endpoint for bidirectional A2A communication."""
        await websocket.accept()
        log_event(logger, "gateway.ws_connected")

        try:
            while True:
                raw = await websocket.receive_json()
                async for chunk in gateway.handle_envelope(raw):
                    await websocket.send_json(chunk)
        except Exception as e:
            log_event(logger, "gateway.ws_error", error_code="INTERNAL_ERROR",
                      state=str(e))
        finally:
            log_event(logger, "gateway.ws_disconnected")

    # --- CANCEL endpoint ---
    @app.post("/cancel")
    async def cancel_endpoint(request: Request):
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=make_error_envelope("unknown", "unknown", BAD_REQUEST.code,
                                            "Invalid JSON body").model_dump(),
            )
        result = await gateway.handle_cancel(Envelope(**raw))
        return JSONResponse(content=result)

    # --- HEARTBEAT endpoint ---
    @app.post("/heartbeat")
    async def heartbeat_endpoint(request: Request):
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=make_error_envelope("unknown", "unknown", BAD_REQUEST.code,
                                            "Invalid JSON body").model_dump(),
            )
        result = await gateway.handle_heartbeat(Envelope(**raw))
        return JSONResponse(content=result)

    # --- Metrics endpoint ---
    @app.get("/metrics")
    async def metrics_endpoint():
        metrics = get_metrics()
        return JSONResponse(content=metrics.summary())

    # --- Health endpoint ---
    @app.get("/health")
    async def health_endpoint():
        return {"status": "ok", "providers": len(gateway.router.routes)}

    # --- Audit query endpoint ---
    @app.get("/audit/{corr_id}")
    async def audit_query(corr_id: str):
        if gateway.session_store.audit:
            entries = gateway.session_store.audit.query_by_corr_id(corr_id)
            return JSONResponse(content=[e.__dict__ for e in entries])
        return JSONResponse(content=[], status_code=404)

    # --- Error codes endpoint ---
    @app.get("/error-codes")
    async def error_codes_endpoint():
        from app.core.errors import all_error_codes
        codes = {}
        for k, v in all_error_codes().items():
            codes[k] = {
                "code": v.code,
                "source": v.source,
                "trigger": v.trigger,
                "recoverable": v.recoverable,
                "retry_recommended": v.retry_recommended,
                "description": v.description,
            }
        return JSONResponse(content=codes)

    # --- Agent Registry endpoints ---
    @app.get("/agents")
    async def list_agents():
        agents = gateway.multi_agent.list_agents()
        return JSONResponse(content=[
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "roles": a.roles,
                "capabilities": a.capabilities,
                "status": a.status,
                "current_tasks": a.current_tasks,
                "max_concurrent_tasks": a.max_concurrent_tasks,
            }
            for a in agents
        ])

    @app.get("/agents/{agent_id}")
    async def get_agent(agent_id: str):
        profile = gateway.multi_agent.get_agent(agent_id)
        if not profile:
            return JSONResponse(status_code=404,
                                content={"error": "Agent not found", "agent_id": agent_id})
        return JSONResponse(content={
            "agent_id": profile.agent_id,
            "name": profile.name,
            "roles": profile.roles,
            "capabilities": profile.capabilities,
            "status": profile.status,
            "current_tasks": profile.current_tasks,
        })

    @app.post("/agents/register")
    async def register_agent(request: Request):
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})
        agent_id = raw.get("agent_id", "")
        if not agent_id:
            return JSONResponse(status_code=400, content={"error": "agent_id is required"})
        profile = AgentProfile(
            agent_id=agent_id,
            name=raw.get("name", agent_id),
            roles=raw.get("roles", ["worker"]),
            capabilities=raw.get("capabilities", []),
            status=raw.get("status", "online"),
        )
        gateway.multi_agent.register_agent(profile, security=gateway.security)
        return JSONResponse(content={"agent_id": agent_id, "status": "registered"})

    @app.get("/delegations")
    async def list_delegations():
        delegations = gateway.multi_agent.list_delegations()
        return JSONResponse(content=[
            {
                "delegation_id": d.delegation_id,
                "source_agent": d.source_agent,
                "target_agent": d.target_agent,
                "task": d.task,
                "pattern": d.pattern,
                "status": d.status,
                "result": d.result,
            }
            for d in delegations
        ])

    return app


def main():
    config = load_config()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()