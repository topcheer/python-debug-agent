# YouTube Video Description

## Title

Python Debug Agent v0.5.0 — Security, Health, Scheduler, Errors, WebSocket (82 Tools)

## Description

Embed an AI debugging assistant into your Flask, FastAPI, or Django app. 82 tools across 27 inspectors, all accessible through natural language chat at /agent.

pip install debug-agent-py

New in v0.5.0:
- Security: auth configs, active sessions, CORS settings
- Health: UP/DOWN/DEGRADED checks for DB, Redis, disk
- Scheduler: APScheduler/Celery beat job listing and history
- Error Tracking: ring buffer captures unhandled exceptions with tracebacks
- WebSocket: active connections, stats, rooms

Plus existing inspectors: Memory (tracemalloc), GC, threads, async tasks, database (SQLAlchemy), Redis, Celery, Flask extensions, Jinja2, Django, signals, HTTP tracking, logging tree, cache stats, outbound HTTP, file descriptors, metrics, warnings.

One pip install. One line of code. Chat with your running app.

Quick Start:
from flask import Flask
from debug_agent import setup_debug_agent
app = Flask(__name__)
setup_debug_agent(app)

Then open localhost:8000/agent

INSPECTOR COVERAGE (27 Inspectors / 82 Tools)

Core: Memory(4), Threads(3), Async(2), Runtime(1), GC(3), System(3), Modules(3)
Web: Framework(2), HTTP Tracker(4), Flask Ext(3), Jinja2(2), FastAPI(1)
Data: Database(2), Redis(4), Django(4), Celery(3)
Infra: Logging(4), Cache(2), HTTP Client(2), FD(3), Metrics(2), Warnings(1), Signals(2)
NEW v0.5: Security(3), Health(2), Scheduler(3), Error Tracking(3), WebSocket(3)

GitHub: github.com/topcheer/python-debug-agent

#python #flask #security #healthcheck #websocket #errorhandling #scheduler #AI #Diagnostics #FastAPI #Django #Redis #Celery #SQLAlchemy #DeveloperTools #DevOps

## Chapters

00:00 Introduction
00:24 Memory (tracemalloc) + GC Stats
03:03 Threads + Async Tasks + Signals
05:43 Database (SQLAlchemy) + Redis
08:22 Flask Routes + Jinja2 + Logging
11:02 HTTP Requests + Cache + Metrics
13:42 Security — Auth, Sessions, CORS
16:21 Health Checks + Scheduler
19:01 Error Tracking + Warnings
21:40 Outbound HTTP + FD + FastAPI
24:20 Comprehensive Multi-Tool Debugging
