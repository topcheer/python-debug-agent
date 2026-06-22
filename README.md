# Python Debug Agent

[![debug-agent-py](https://img.shields.io/pypi/v/debug-agent-py.svg)](https://pypi.org/project/debug-agent-py/)
![Tools](https://img.shields.io/badge/tools-68-blue)
![Inspectors](https://img.shields.io/badge/inspectors-24-green)

An AI-powered runtime debugging agent that embeds directly into your Python web application. Add one dependency, configure an LLM key, and chat with your live app at `/agent` to inspect memory, threads, GC, modules, database connections, Redis, Django models/URLs, Celery tasks, Flask extensions, Jinja2 templates, signals, routes, HTTP requests, and more — **68 diagnostic tools across 24 inspectors**.

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
- **68 diagnostic tools** across **24 inspectors**
- Works with Flask, FastAPI, and Django
- Zero external dependencies (no Datadog, no Grafana, no APM)

## Inspectors & Tools (68)

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
| `get_thread_stacks` | Current frame/stack for all threads |

### Database Inspector
| Tool | Description |
|------|-------------|
| `get_sqlalchemy_engines` | Find SQLAlchemy engines and pool status |
| `get_db_connections` | Inspect database connection pools |
| `get_db_pool_config` | Pool configuration: size, timeout, recycle settings |

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
| `get_pending_callbacks` | List scheduled callbacks on the event loop |

### Runtime Inspector
| Tool | Description |
|------|-------------|
| `get_memory_info` | Process memory info (RSS, VMS, shared) |
| `get_cpu_usage` | CPU usage percentage |
| `get_python_info` | Python version, implementation, executable path |
| `get_open_fds` | Open file descriptor count and limits |

### System Inspector
| Tool | Description |
|------|-------------|
| `get_system_info` | Hostname, platform, CPU cores, disk |
| `get_environment_variables` | Environment variables (masked secrets) |
| `get_disk_usage` | Disk usage for the working directory |

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

### Redis Inspector
| Tool | Description |
|------|-------------|
| `get_redis_info` | Redis server info: memory, clients, persistence |
| `get_redis_keys` | Scan Redis keyspace with pattern matching |
| `get_redis_config` | Redis runtime configuration (CONFIG GET) |
| `get_redis_slowlog` | Redis slow query log entries |

### Django Inspector
| Tool | Description |
|------|-------------|
| `get_django_models` | List Django models with app label, table name, field count |
| `get_django_urls` | List all URL patterns with view names and namespaces |
| `get_django_settings` | Key Django settings (DBs, INSTALLED_APPS, MIDDLEWARE) |
| `get_django_migrations` | Migration status per app: applied vs pending |

### Celery Inspector
| Tool | Description |
|------|-------------|
| `get_celery_tasks` | List registered Celery tasks with routing info |
| `get_celery_workers` | Active Celery workers with pool and concurrency |
| `get_celery_queues` | Queue depth and message stats per queue |

### Flask Extensions Inspector
| Tool | Description |
|------|-------------|
| `get_flask_extensions` | List registered Flask extensions and their bindings |
| `get_flask_blueprints` | List Flask blueprints with URL prefixes and routes |
| `get_flask_config` | Flask configuration object values (secrets masked) |

### Jinja2 Inspector
| Tool | Description |
|------|-------------|
| `get_jinja_templates` | List loaded Jinja2 templates with loader paths |
| `get_jinja_filters` | List registered Jinja2 filters, tests, and globals |

### Signals Inspector
| Tool | Description |
|------|-------------|
| `get_signal_handlers` | List Python signal handlers registered via signal module |
| `get_django_signals` | List Django signal receivers connected to senders |

### WSGI/ASGI Inspector
| Tool | Description |
|------|-------------|
| `get_wsgi_info` | WSGI server details (Gunicorn/uWSGI workers, config) |
| `get_asgi_apps` | List ASGI application scope and middleware chain |

### Logging Inspector
| Tool | Description |
|------|-------------|
| `get_logging_tree` | Python logging module logger hierarchy and levels |
| `get_recent_logs` | Recent log entries from the built-in ring buffer |
| `get_logging_config` | Current logging configuration (handlers, formatters, levels) |
| `set_log_level` | Dynamically set the log level for a named logger |

### Cache Inspector
| Tool | Description |
|------|-------------|
| `get_cache_info` | Stats for registered caches (hit rate, miss count, key count) |
| `get_cache_keys` | List keys from a registered cache with optional prefix filter |
| `clear_cache` | Clear all entries from a registered cache |

### Outbound HTTP Inspector
| Tool | Description |
|------|-------------|
| `get_http_pool_stats` | HTTP client connection pool stats (connections, keepalive, timeouts) |
| `get_outbound_summary` | Aggregated outbound HTTP call stats (total, avg latency, error rate) |

### File Descriptor Inspector
| Tool | Description |
|------|-------------|
| `get_fd_count` | Current number of open file descriptors |
| `get_fd_limit` | File descriptor soft and hard limits (RLIMIT_NOFILE) |
| `get_fd_list` | List open file descriptors with type and details |

### Metrics Inspector
| Tool | Description |
|------|-------------|
| `get_registered_metrics` | List all registered metrics from prometheus_client |
| `get_metric_value` | Get current value of a specific metric by name |

### FastAPI Inspector
| Tool | Description |
|------|-------------|
| `get_fastapi_openapi` | List FastAPI routes, schemas, and OpenAPI spec details |

### Warnings Inspector
| Tool | Description |
|------|-------------|
| `get_warnings` | List captured Python warnings with category, message, and location |

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

The demo uses **Flask** + **redis-py** + **SQLAlchemy** + **Celery**. Start Redis with Docker Compose first:

### Docker Compose

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: redis-server --save 60 1 --loglevel warning
```

```bash
docker compose up -d
```

### Start the app

```bash
export LLM_API_KEY=your-key
cd demo && python app.py
# Open http://localhost:8000/agent
```

## PyPI

[![debug-agent-py](https://img.shields.io/pypi/v/debug-agent-py.svg)](https://pypi.org/project/debug-agent-py/)

## License

MIT
