"""OpenTelemetry GenAI semantic convention attribute constants.

Based on the OpenTelemetry GenAI semantic conventions spec.
"""

from __future__ import annotations

# Service attributes
SERVICE_NAME = "service.name"

# GenAI operation attributes
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
GEN_AI_REQUEST_TEMPERATURE = "gen_ai.request.temperature"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

# Agent Gateway custom attributes
AGW_AGENT_ID = "agw.agent.id"
AGW_EXECUTION_ID = "agw.execution.id"
AGW_TOOL_NAME = "agw.tool.name"
AGW_TOOL_TYPE = "agw.tool.type"
AGW_STOP_REASON = "agw.stop_reason"
AGW_COST_USD = "agw.cost_usd"
AGW_SCHEDULE_ID = "agw.schedule.id"
AGW_QUEUE_BACKEND = "agw.queue.backend"
AGW_WORKER_ID = "agw.worker.id"

# Operation names
OP_AGENT_INVOKE = "agent.invoke"
OP_LLM_CALL = "llm.call"
OP_TOOL_EXECUTE = "tool.execute"
OP_OUTPUT_VALIDATE = "output.validate"
OP_PROMPT_ASSEMBLE = "prompt.assemble"
OP_NOTIFICATION_SEND = "notification.send"
OP_QUEUE_PROCESS = "queue.process"
