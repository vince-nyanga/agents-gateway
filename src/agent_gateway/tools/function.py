"""Function tool executor — runs Python handlers (@gw.tool and handler.py)."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_gateway.engine.models import ToolContext
from agent_gateway.workspace.registry import CodeTool
from agent_gateway.workspace.tool import ToolDefinition

logger = logging.getLogger(__name__)


async def execute_code_tool(
    tool: CodeTool,
    arguments: dict[str, Any],
    context: ToolContext,
) -> Any:
    """Execute a @gw.tool() decorated function.

    Handles both sync and async functions. Injects ToolContext if the
    function signature accepts a 'context' parameter. Filters arguments
    to only those accepted by the function signature.
    """
    fn = tool.fn
    sig = inspect.signature(fn)
    params = sig.parameters

    # Filter arguments to only those the function accepts.
    # Pass all arguments if **kwargs is present.
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if has_var_keyword:
        kwargs = dict(arguments)
    else:
        kwargs = {k: v for k, v in arguments.items() if k in params}

    # Inject context if the function accepts it
    if "context" in params:
        kwargs["context"] = context

    if asyncio.iscoroutinefunction(fn):
        return await fn(**kwargs)
    else:
        return await asyncio.to_thread(fn, **kwargs)


async def execute_function_tool(
    tool: ToolDefinition,
    arguments: dict[str, Any],
    context: ToolContext,
) -> Any:
    """Execute a file-based function tool (handler.py).

    Loads the handler module, finds the `handle` function, and calls it.
    Raises RuntimeError if the handler cannot be loaded.
    """
    if tool.handler_path is None:
        raise RuntimeError(f"Tool '{tool.name}' has no handler.py")

    handler_fn = load_handler(tool.handler_path, tool.name)
    if handler_fn is None:
        raise RuntimeError(f"Tool '{tool.name}' handler could not be loaded")

    if asyncio.iscoroutinefunction(handler_fn):
        return await handler_fn(arguments, context)
    else:
        return await asyncio.to_thread(handler_fn, arguments, context)


def load_handler(handler_path: Path, tool_name: str) -> Callable[..., Any] | None:
    """Import handler.py and return the `handle` function.

    Returns None if import fails or `handle` is not found.
    Errors are logged but not raised.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            f"agent_gateway.tools._handlers.{tool_name}",
            handler_path,
        )
        if spec is None or spec.loader is None:
            logger.error("Cannot create module spec for handler: %s", handler_path)
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error(
            "Failed to import handler for tool '%s': %s: %s",
            tool_name,
            type(e).__name__,
            e,
        )
        return None

    handle_fn = getattr(module, "handle", None)
    if handle_fn is None:
        logger.error("handler.py for tool '%s' has no 'handle' function", tool_name)
        return None

    if not callable(handle_fn):
        logger.error("'handle' in handler.py for tool '%s' is not callable", tool_name)
        return None

    result: Callable[..., Any] = handle_fn
    return result
