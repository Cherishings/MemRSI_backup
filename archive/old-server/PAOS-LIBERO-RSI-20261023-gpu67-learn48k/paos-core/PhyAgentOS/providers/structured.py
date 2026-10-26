"""Schema-guided model calls with bounded repair and input-free diagnostics."""
from __future__ import annotations

import asyncio
import json

import json_repair
from pydantic import ValidationError


class StructuredResponseError(ValueError):
    def __init__(self, issues):
        self.validation_issues = issues
        super().__init__("Structured response rejected: " + json.dumps(issues))


async def complete_typed(
    *, provider, model, result_type, system_prompt, user_content,
    timeout_s=180.0, max_tokens=4096,
):
    schema = result_type.model_json_schema()
    messages = [
        {"role": "system", "content": system_prompt + "\n\nOutput JSON Schema:\n" + json.dumps(schema)},
        {"role": "user", "content": user_content},
    ]
    deadline = asyncio.get_running_loop().time() + timeout_s
    issues = []
    for attempt in range(2):
        kwargs = dict(messages=messages, model=model, temperature=0.0, max_tokens=max_tokens)
        if getattr(provider, "structured_outputs", False):
            call = provider.chat_structured(
                **kwargs, schema=schema, schema_name=result_type.__name__,
            )
        else:
            call = provider.chat_with_retry(**kwargs, tools=None)
        response = await asyncio.wait_for(
            call, timeout=max(.01, deadline - asyncio.get_running_loop().time()),
        )
        if response.finish_reason == "error":
            raise RuntimeError(response.content or "structured model request failed")
        if response.finish_reason == "length":
            raise StructuredResponseError([{"loc": [], "type": "output_token_limit"}])
        try:
            data = json_repair.loads(response.content or "")
            if not isinstance(data, dict):
                raise StructuredResponseError([{"loc": [], "type": "json_object_required"}])
            return result_type.model_validate(data)
        except ValidationError as exc:
            # Deliberately omit input values and exception context from diagnostics.
            issues = [{"loc": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                      for e in exc.errors(include_input=False, include_context=False)]
        except StructuredResponseError as exc:
            issues = exc.validation_issues
        if attempt == 0:
            messages.extend([
                {"role": "assistant", "content": response.content or "{}"},
                {"role": "user", "content": (
                    "Your JSON failed schema validation at these fields: " + json.dumps(issues)
                    + ". Return a complete corrected JSON object following the schema and original evidence. "
                    "Do not change the underlying task outcome to satisfy formatting."
                )},
            ])
    raise StructuredResponseError(issues)
