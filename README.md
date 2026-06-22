# Python Debug Agent

An AI-powered runtime debugging agent that embeds directly into your Python web application. Add one dependency, configure an LLM key, and chat with your live app at `/agent` to inspect memory, threads, GC, modules, database connections, routes, HTTP requests, and more.

## Quick Start

### 1. Install

```bash
pip install debug-agent-py
```

### 2. Integrate (Flask)

```python
from flask import Flask
from debug_agent import setup_debug_agent

app = Flask(__name__)

# One line to integrate
setup_debug_agent(app)
```

### 3. Configure LLM

```bash
export LLM_API_KEY=your-key
export LLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4  # default
export LLM_MODEL=glm-5.2                                          # default
```

Supports any OpenAI-compatible endpoint.

### 4. Run and open

```
http://localhost:8000/agent
```

## Features

- **Streaming AI responses** with real-time tool call badges (pending / success / error)
- **Context compression** — automatically summarizes old conversation when token limit is approached
- **Dark-themed chat UI** with full markdown rendering (tables, code blocks, lists)
- **Max tool rounds** (25) with forced final summary when limit is reached
- **34 diagnostic tools** across 10 inspectors
- Works with Flask, FastAPI, and Django

## Inspectors & Tools (34)

### Memory Inspector
| Tool | Description |
|------|-------------|
| `get_tracemalloc_stats` | Python tracemalloc top allocations by file/line |
| `get_object_counts` | Count objects by type via gc |
| `get_gc_stats` | gc.get_stats() generation details |
| `get_ref_cycles` | Count reference cycles detected by gc |
| `trigger_gc` | Force garbage collection |

### Threads Inspector
| Tool | Description |
|------|-------------|
| `get_thread_info` | List all threads with name, daemon, alive status |
| `get_thread_count` | Active thread count |
| `get_thread_summary` | Thread state distribution |

### Database Inspector
| Tool | Description |
|------|-------------|
| `get_sqlalchemy_engines` | Find SQLAlchemy engines and pool status |
| `get_db_connections` | Inspect database connection pools |

### Modules Inspector
| Tool | Description |
|------|-------------|
| `get_loaded_modules` | List loaded Python modules (sys.modules) with versions |
| `get_module_count` | Total loaded module count |
| `get_installed_packages` | List installed packages from pip |

### Async Tasks Inspector
| Tool | Description |
|------|-------------|
| `get_async_tasks` | List pending asyncio tasks |
| `get_event_loop_info` | Event loop details: type, running state |

### Runtime Inspector
| Tool | Description |
|------|-------------|
| `get_memory_info` | Process memory info (RSS, VMS, shared) |
| `get_cpu_usage` | CPU usage percentage |
| `get_python_info` | Python version, implementation, executable path |

### System Inspector
| Tool | Description |
|------|-------------|
| `get_system_info` | Hostname, platform, CPU cores, disk |
| `get_environment_variables` | Environment variables (masked secrets) |
| `get_disk_usage` | Disk usage for working directory |

### Framework Inspector
| Tool | Description |
|------|-------------|
| `get_routes` | List all registered web routes/endpoints |
| `get_middleware` | List registered middleware |

### HTTP Tracker Inspector
| Tool | Description |
|------|-------------|
| `get_recent_requests` | Recent HTTP requests ring buffer |
| `get_slow_requests` | Slowest requests by duration |
| `get_error_requests` | Error requests (4xx/5xx) |
| `get_request_stats` | P50/P95/P99 latency, error rate |

## Custom Tools

```python
from debug_agent import debug_tool

@debug_tool('check_redis', 'Check Redis connection')
def check_redis():
    return {'connected': True}
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/coding/paas/v4` | LLM endpoint |
| `LLM_API_KEY` | (required) | API key |
| `LLM_MODEL` | `glm-5.2` | Model name |
| `LLM_MAX_TOOL_ROUNDS` | `25` | Max tool-calling rounds |
| `LLM_CONTEXT_WINDOW_TOKENS` | `100000` | Context window size |

## Run the Demo

```bash
export LLM_API_KEY=your-key
cd demo && python app.py
# Open http://localhost:8000/agent
```

## PyPI

[![debug-agent-py](https://img.shields.io/pypi/v/debug-agent-py.svg)](https://pypi.org/project/debug-agent-py/)

## License

MIT
