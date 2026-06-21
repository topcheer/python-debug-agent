# Python Debug Agent

An AI-powered runtime debugging agent that embeds directly into your Python web application. Add one dependency, configure an LLM key, and chat with your live app at `/agent` to inspect memory, threads, routes, HTTP requests, GC stats, and more.

## Quick Start

### 1. Install

```bash
pip install debug-agent[fastapi]
```

### 2. Integrate (FastAPI)

```python
from fastapi import FastAPI
from debug_agent.middleware import create_fastapi_router

app = FastAPI()

# One line to integrate
app.include_router(create_fastapi_router())
```

### 3. Configure LLM

```bash
export LLM_API_KEY=your-key
export LLM_BASE_URL=https://api.openai.com/v1  # optional
export LLM_MODEL=gpt-4o                         # optional
```

### 4. Run and open

```
http://localhost:8000/agent
```

## Framework Integrations

### FastAPI / Starlette

```python
from debug_agent.middleware import create_fastapi_router
app.include_router(create_fastapi_router())
```

### Flask

```python
from flask import Flask
from debug_agent.middleware import create_flask_blueprint
app = Flask(__name__)
app.register_blueprint(create_flask_blueprint())
```

### Any ASGI App (Starlette Mount)

```python
from starlette.routing import Mount
from debug_agent.middleware import create_starlette_app
routes = [Mount("/agent", app=create_starlette_app())]
```

## Built-in Tools (18+)

| Tool | Description |
|------|-------------|
| `get_gc_stats` | GC collection counts per generation |
| `get_memory_summary` | RSS, object counts, top types |
| `trigger_gc` | Force GC and show before/after |
| `get_thread_summary` | Thread count, names, daemon status |
| `get_thread_dump` | Stack traces for all threads |
| `get_runtime_info` | Python version, platform, PID |
| `get_memory_allocations` | tracemalloc top allocations |
| `get_routes` | List all web routes/endpoints |
| `get_middleware` | List registered middleware |
| `get_installed_packages` | Installed pip packages |
| `get_environment_variables` | Environment variables (masked secrets) |
| `get_recent_requests` | HTTP request ring buffer |
| `get_slow_requests` | Slowest requests sorted by duration |
| `get_error_requests` | Error requests (4xx/5xx) |
| `get_request_stats` | P50/P95/P99 latency, error rate |
| `get_process_info` | PID, CPU time, container detection |
| `get_system_info` | OS, CPU cores, load average |
| `get_disk_usage` | Disk usage for working directory |

## Custom Tools

```python
from debug_agent import debug_tool, ToolParam

@debug_tool("check_db_pool", "Check database connection pool stats")
def check_db_pool() -> dict:
    return {"active": 5, "idle": 10, "max": 20}
```

That's it. The tool is auto-discovered and made available to the LLM.

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `DEBUG_AGENT_ENABLED` | `true` | Enable/disable |
| `DEBUG_AGENT_BASE_PATH` | `/agent` | URL path |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM endpoint |
| `LLM_API_KEY` | (required) | API key |
| `LLM_MODEL` | `gpt-4o` | Model name |
| `LLM_TEMPERATURE` | `0.3` | Sampling temp |
| `LLM_MAX_TOOL_ROUNDS` | `10` | Max tool rounds |

## Run the Demo

```bash
pip install -e ".[dev]"
export LLM_API_KEY=your-key
python demo/app.py
# Open http://localhost:8000/agent
```

## License

MIT
