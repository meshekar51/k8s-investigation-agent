"""Observability (transcript step 8): Prometheus metrics scraped from /metrics.

Grafana questions these answer:
  - Is the agent healthy?           sre_agent_investigations_total{status}
  - Is it slow?                     sre_agent_investigation_seconds
  - What does it cost?              sre_agent_llm_tokens_total{type}
  - What is it actually doing?      sre_agent_tool_calls_total{tool}
  - What breaks most in my cluster? sre_agent_investigations_total{category}
"""

from prometheus_client import Counter, Histogram

INVESTIGATIONS = Counter(
    "sre_agent_investigations_total", "Investigations finished", ["status", "category", "env"]
)
DURATION = Histogram(
    "sre_agent_investigation_seconds", "End-to-end investigation time", ["env"],
    buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 300),
)
TOOL_CALLS = Counter("sre_agent_tool_calls_total", "Tool calls made by the agent", ["tool", "env"])
TOKENS = Counter("sre_agent_llm_tokens_total", "LLM tokens used", ["type", "env"])


def record(result, env: str) -> None:
    status = "error" if result.error else ("ok" if result.footer else "no_footer")
    category = (result.footer or {}).get("category", "NONE")
    INVESTIGATIONS.labels(status=status, category=category, env=env).inc()
    DURATION.labels(env=env).observe(result.duration_s)
    for name in result.tool_calls:
        TOOL_CALLS.labels(tool=name, env=env).inc()
    TOKENS.labels(type="input", env=env).inc(result.input_tokens)
    TOKENS.labels(type="output", env=env).inc(result.output_tokens)
