"""Chat endpoint — the core API route."""

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sse_starlette.sse import EventSourceResponse

from ...bus import live_bus
from ...claude.client import ClaudeClient, MODE_YOLO
from ...preferences import resolve_execute_args
from ..auth import get_api_user
from ..models import ChatRequest, ChatResponse

logger = structlog.get_logger()

router = APIRouter()


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, user: dict = Depends(get_api_user)):
    """Send a message to Claude. Returns full JSON response or SSE stream."""
    claude: ClaudeClient = request.app.state.claude
    mysql = request.app.state.mysql
    es = request.app.state.es
    settings = request.app.state.settings

    user_id = user["user_id"]

    # Load user preferences from MySQL
    exec_args = await resolve_execute_args(mysql, settings, user_id)
    cwd = body.cwd or exec_args["working_directory"]

    # Resolve effective model: request body overrides user preference
    if body.model:
        exec_args["model"] = body.model

    # Resolve effective mode: request body overrides user preference
    effective_mode = body.mode or exec_args["mode"]
    # Approve mode requires Telegram buttons — fall back to yolo in WebUI
    if effective_mode == "approve":
        logger.warning("Approve mode not available in WebUI, falling back to yolo")
        effective_mode = "yolo"

    # Resolve session
    session_id = body.session_id
    if not session_id and not body.force_new:
        existing = await mysql.get_active_session(user_id, cwd, channel="web")
        if existing:
            session_id = existing["session_id"]

    # Acquire cross-channel execution lock (only for known sessions)
    if session_id:
        acquired = await mysql.acquire_running_lock(session_id, "web")
        if not acquired:
            active_ch = await mysql.get_running_channel(session_id)
            source = "Telegram" if active_ch == "telegram" else "einem anderen Kanal"
            raise HTTPException(
                status_code=409,
                detail=f"Diese Session wird gerade von {source} ausgeführt. Warte bis sie fertig ist oder brich sie ab.",
            )

    if body.stream:
        return EventSourceResponse(
            _stream_chat(claude, mysql, es, settings, body, user_id, session_id, cwd, request, exec_args, effective_mode),
            media_type="text/event-stream",
        )

    # Non-streaming: wait for full response
    try:
        result = await claude.execute(
            prompt=body.message,
            user_id=user_id,
            session_id=session_id,
            cwd=cwd,
            mode=effective_mode,
            model=exec_args["model"],
            profile=exec_args["profile"],
            max_turns=exec_args["max_turns"],
            thinking=exec_args["thinking"],
            thinking_budget=exec_args["thinking_budget"],
            budget=exec_args["budget"],
        )
    except TimeoutError as e:
        if session_id:
            await mysql.release_running_lock(session_id)
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        if session_id:
            await mysql.release_running_lock(session_id)
        logger.error("Chat failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    await _persist(mysql, es, user_id, result, body.message, cwd)
    if session_id:
        await mysql.release_running_lock(session_id)

    # Hidden sessions (e.g. NER extraction) are deactivated so they
    # don't appear in the user's sidebar
    if body.hidden and session_id:
        await mysql.deactivate_session(session_id, user_id)

    return ChatResponse(
        content=result["content"] or "",
        session_id=result["session_id"],
        cost=result["cost"],
        duration_ms=result["duration_ms"],
        tools_used=result["tools_used"],
    )


@router.get("/sessions/{session_id}/stream")
async def session_stream(
    session_id: str,
    request: Request,
    user: dict = Depends(get_api_user),
):
    """SSE stream for live events of a running session.

    Web clients subscribe here to receive real-time tool/text events whether
    the execution was triggered from Telegram or from the web itself.
    Automatically closes when the client disconnects.
    """
    return EventSourceResponse(
        _session_event_stream(session_id, request),
        media_type="text/event-stream",
    )


async def _session_event_stream(session_id: str, request: Request):
    """Async generator: subscribe to LiveEventBus and forward events as SSE."""
    q = live_bus.subscribe(session_id)
    logger.debug("SSE subscriber connected", session_id=session_id)
    try:
        # Send an initial ping so the client knows the connection is alive
        yield {"event": "ping", "data": json.dumps({"event": "ping", "session_id": session_id})}

        while True:
            # Check for client disconnect every second
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Keep-alive ping every second while waiting
                yield {"event": "ping", "data": json.dumps({"event": "ping"})}
                continue

            # Use get (not pop) so "event" stays in the JSON payload — the frontend
            # ignores the SSE event: field and reads event type from the data JSON.
            event_type = event.get("event", "message")
            yield {"event": event_type, "data": json.dumps(event, ensure_ascii=False)}

            # Done event signals end of this execution — close the stream
            if event_type == "done":
                break
    finally:
        live_bus.unsubscribe(session_id, q)
        logger.debug("SSE subscriber disconnected", session_id=session_id)


async def _stream_chat(claude, mysql, es, settings, body, user_id, session_id, cwd, request: Request, exec_args: dict | None = None, effective_mode: str = "yolo"):
    """Async generator that yields SSE events during Claude execution.

    The caller (route handler) acquires the cross-channel lock before starting
    this generator.  We release it here in the finally block so it is always
    freed — regardless of whether the client disconnects early, an error occurs,
    or execution completes normally.
    """
    event_queue: asyncio.Queue = asyncio.Queue()
    result_holder: dict = {}
    _effective_session: list[str | None] = [session_id]  # mutable container for finally
    _tool_events: list[dict] = []  # collected tool events for DB persistence

    # Persist prompt immediately so web polling / other subscribers see it
    pending_message_id: int | None = None
    if session_id:
        try:
            pending_message_id = await mysql.save_message_prompt(
                session_id, user_id, body.message
            )
        except Exception:
            pass

    async def on_message(msg_type: str, content: str, extra: dict = None):
        extra = extra or {}
        if msg_type == "tool_start":
            ev = {"event": "tool_start", "tool": content, "input": extra}
            _tool_events.append({
                "tool": content,
                "input": extra,
                "status": "running",
                "isBackgroundTask": False,
            })
        elif msg_type == "tool_result":
            ev = {
                "event": "tool_result",
                "tool": content,
                "success": extra.get("success", True),
                "duration": extra.get("duration", 0),
                "preview": extra.get("preview", ""),
            }
            # Update the matching running tool event
            for t in reversed(_tool_events):
                if t["tool"] == content and t["status"] == "running":
                    t["status"] = "done" if extra.get("success", True) else "error"
                    t["success"] = extra.get("success", True)
                    t["duration"] = extra.get("duration", 0)
                    t["preview"] = extra.get("preview", "")
                    break
        elif msg_type == "text":
            ev = {"event": "text", "content": content}
        elif msg_type == "thinking_text":
            ev = {"event": "thinking_text", "content": content}
        elif msg_type == "compaction":
            ev = {"event": "compaction", "content": content, **extra}
        elif msg_type == "context_usage":
            ev = {"event": "context_usage", **extra}
        else:
            return

        event_queue.put_nowait(ev)

        # Also publish to LiveEventBus for any other web subscribers on this session
        if session_id and live_bus.has_subscribers(session_id):
            await live_bus.publish(session_id, dict(ev))

    async def run_claude():
        try:
            result = await claude.execute(
                prompt=body.message,
                user_id=user_id,
                session_id=session_id,
                cwd=cwd,
                on_message=on_message,
                mode=effective_mode,
                model=exec_args["model"] if exec_args else (settings.claude_default_model or None),
                profile=exec_args.get("profile") if exec_args else None,
                max_turns=exec_args["max_turns"] if exec_args else None,
                thinking=exec_args["thinking"] if exec_args else False,
                thinking_budget=exec_args.get("thinking_budget", 10_000) if exec_args else 10_000,
                budget=exec_args.get("budget") if exec_args else None,
            )
            result_holder.update(result)
        except Exception as e:
            event_queue.put_nowait({"event": "error", "content": str(e)})
        finally:
            event_queue.put_nowait(None)  # Sentinel

    task = asyncio.create_task(run_claude())
    if session_id:
        claude.register_task(session_id, task)

    try:
        # Stream events to this web client.
        # We poll with a short timeout so we can emit keep-alive "thinking" events
        # while Claude is working — without them the browser SSE connection looks
        # frozen for 25-60s and the user believes sending failed.
        elapsed = 0
        while True:
            # Abort early if the web client has disconnected (e.g. browser closed,
            # Next.js server restarted).  This cancels the Claude task and ensures
            # the finally block releases the lock promptly.
            if await request.is_disconnected():
                logger.info("SSE client disconnected — cancelling task", session_id=session_id)
                task.cancel()
                break

            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=3.0)
            except asyncio.TimeoutError:
                elapsed += 3
                # Send a visible status ping every 3 s while waiting for Claude
                yield {
                    "event": "thinking",
                    "data": json.dumps({"event": "thinking", "elapsed_s": elapsed}),
                }
                continue

            if item is None:
                break
            # Use get (not pop) so "event" stays in the JSON payload
            event_type = item.get("event", "message")
            yield {"event": event_type, "data": json.dumps(item, ensure_ascii=False)}

        await task

        # Persist + final "done" event
        if result_holder:
            effective_session = result_holder.get("session_id") or session_id or "unknown"
            cost = result_holder.get("cost", 0)
            duration_ms = result_holder.get("duration_ms", 0)
            tools_used = result_holder.get("tools_used", [])
            response = result_holder.get("content", "")
            model = result_holder.get("model")
            usage = result_holder.get("usage", {}) or {}

            context_tokens = result_holder.get("context_tokens", 0) or 0
            context_max_tokens = result_holder.get("context_max_tokens", 0) or 0
            if effective_session != "unknown":
                await mysql.save_session(effective_session, user_id, cwd,
                                         cost=cost, turns=1, messages=1,
                                         context_tokens=context_tokens,
                                         context_max_tokens=context_max_tokens)

            # Persist tool events (strip large input data to keep DB lean)
            persisted_tools = [
                {k: v for k, v in t.items() if k != "input"}
                for t in _tool_events
            ] if _tool_events else None

            if pending_message_id:
                await mysql.update_message_response(
                    message_id=pending_message_id,
                    response=response,
                    cost=cost,
                    duration_ms=duration_ms,
                    model=model,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    session_id=effective_session if effective_session != session_id else None,
                    tools_json=persisted_tools,
                )
            else:
                await mysql.save_message(
                    session_id=effective_session, user_id=user_id,
                    prompt=body.message, response=response,
                    cost=cost, duration_ms=duration_ms, model=model,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    tools_json=persisted_tools,
                )

            if cost > 0:
                await mysql.track_cost(user_id, cost)
            for tool in tools_used:
                await mysql.save_tool_usage(effective_session, tool)

            await es.log_conversation(effective_session, user_id, "user", body.message)
            await es.log_conversation(effective_session, user_id, "assistant", response,
                                      tools_used=tools_used, cost=cost, model=model)

            done_payload = {
                "session_id": effective_session,
                "cost": cost,
                "duration_ms": duration_ms,
                "tools_used": tools_used,
            }

            # Notify any other bus subscribers (e.g. second browser tab)
            if session_id and live_bus.has_subscribers(session_id):
                await live_bus.publish(session_id, {"event": "done", **done_payload})

            yield {
                "event": "done",
                "data": json.dumps({"event": "done", "content": response, **done_payload}, ensure_ascii=False),
            }
    finally:
        # Release cross-channel lock and unregister task
        if session_id:
            claude.unregister_task(session_id)
            await mysql.release_running_lock(session_id)


async def _persist(mysql, es, user_id, result, prompt, cwd):
    """Persist message to MySQL and ES (non-streaming fallback)."""
    session_id = result.get("session_id") or "unknown"
    cost = result.get("cost", 0)
    duration_ms = result.get("duration_ms", 0)
    tools_used = result.get("tools_used", [])
    response = result.get("content", "")

    context_tokens = result.get("context_tokens", 0) or 0
    context_max_tokens = result.get("context_max_tokens", 0) or 0
    if session_id != "unknown":
        await mysql.save_session(session_id, user_id, cwd,
                                 cost=cost, turns=1, messages=1,
                                 context_tokens=context_tokens,
                                 context_max_tokens=context_max_tokens)

    model = result.get("model")
    usage = result.get("usage", {}) or {}
    await mysql.save_message(
        session_id=session_id, user_id=user_id,
        prompt=prompt, response=response,
        cost=cost, duration_ms=duration_ms, model=model,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
    )
    if cost > 0:
        await mysql.track_cost(user_id, cost)
    for tool in tools_used:
        await mysql.save_tool_usage(session_id, tool)

    await es.log_conversation(session_id, user_id, "user", prompt)
    await es.log_conversation(session_id, user_id, "assistant", response,
                              tools_used=tools_used, cost=cost)
