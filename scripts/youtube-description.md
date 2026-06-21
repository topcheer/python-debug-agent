# YouTube Video Description

## Title

Python Debug Agent — AI-Powered In-Process Diagnostics for Flask/FastAPI (10 Inspectors / 30+ Tools)

## Description

Chat with your LIVE Python application at runtime. The Python Debug Agent embeds directly into your Flask or FastAPI app and gives an AI assistant access to 30+ diagnostic tools across 10 inspectors — memory profiler, threads, modules, database, async tasks, GC, runtime, system, framework routes, and HTTP request tracking.

No external agents. No attach-to-process. No separate monitoring stack. Just one pip install, one line of code, and you're chatting with your running app.

### What you'll see in this demo

**Section 1 — Python Runtime + Memory + GC**
Python version, memory summary, GC statistics, tracemalloc allocations, process info, disk usage, and forcing a garbage collection — all through natural language.

**Section 2 — Threads + Async Tasks**
Enumerating all threads with daemon/alive status, per-thread tracebacks, asyncio event loop detection, and pending task listing.

**Section 3 — Modules + Dependencies**
Loaded module inventory with versions, import statistics (largest modules by file size), module detail inspection, installed package listing, and Python path.

**Section 4 — Framework Routes + HTTP Request Tracking**
Discovering all Flask routes, analyzing recent HTTP traffic with P50/P95/P99 latency, identifying slow and error requests.

**Section 5 — Database + Environment**
SQLAlchemy engine detection, connection pool inspection (checked-in/out/overflow), and environment variable listing with secret masking.

**Section 6 — Object Analysis + System**
Live object counts by type, reference cycle detection, GC generation details, and system info (OS, CPU, load average).

**Section 7 — Comprehensive Debugging**
Multi-tool correlation: runtime + memory + GC + threads + HTTP requests + modules + objects — all in one analysis.

### Quick Start

```python
# app.py
from flask import Flask
from debug_agent.middleware import create_flask_blueprint

app = Flask(__name__)
app.register_blueprint(create_flask_blueprint())  # one line!

app.run(port=8000)
```

Open `http://localhost:8000/agent` and start chatting with your app.

### Features

- 30+ diagnostic tools across 10 inspectors
- Streaming AI responses with real-time tool call badges
- LLM-based context compression for long conversations (75% threshold)
- Custom tool registration via @debug_tool decorator
- Works with any OpenAI-compatible LLM endpoint (Z.ai GLM-5.2, OpenAI, etc.)
- Zero external dependencies (no Datadog, no AppDynamics, no Grafana)
- Dark-themed chat UI built-in (single HTML page, no frontend framework)
- SSE streaming with tool badges and context compression notices

### Inspector Coverage

| Inspector | Tools | What it inspects |
|-----------|-------|-----------------|
| Runtime | 7 | Python version, GC, memory, threads, tracemalloc |
| System | 4 | Process info, system info, disk usage, Python path |
| Memory Profiler | 4 | tracemalloc stats, object counts, GC stats, ref cycles |
| Threads | 3 | Thread info, count, per-thread tracebacks |
| Modules | 3 | Loaded modules, import stats, module detail |
| Database | 2 | SQLAlchemy engines, connection pools |
| Async Tasks | 2 | Pending asyncio tasks, event loop info |
| Framework | 4 | Routes, middleware, installed packages, env vars |
| HTTP Requests | 4 | Recent requests, slow requests, errors, stats |
| HTTP Tracker | 4 | Request ring buffer, latency percentiles, error rate |

### GitHub

https://github.com/topcheer/python-debug-agent

### Tags

#python #flask #fastapi #AI #Debugging #Diagnostics #Python #LLM #GLM #DeveloperTools #DevOps #ApplicationMonitoring #AIOps #Observability #PythonDebugging #Flask #FastAPI #OpenSource

## Chapters

00:00 Introduction
01:15 Python Runtime — Memory, GC, Tracemalloc
03:20 Threads + Async Tasks
05:30 Modules + Dependencies
07:10 Framework Routes + HTTP Request Tracking
09:15 Database + Environment
10:50 Object Analysis + System Info
12:20 Comprehensive Multi-Tool Debugging
14:00 Summary + Quick Start Guide

---

## Thumbnail Text (for image)

Python Debug Agent
Chat with your LIVE app
30+ tools / 10 inspectors

---

## Playlist

AI Debug Agents Collection
(Spring / .NET / Go / Node.js / Python / Ruby)

---

## Category

Science & Technology

## Language

English

## Visibility

Public

## Made for Kids

No
