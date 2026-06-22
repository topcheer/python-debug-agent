const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');

/**
 * Python Debug Agent v0.5.0 — Full demo recording (82 tools / 20 inspectors)
 *
 * 10 sections using NATURAL LANGUAGE prompts (no explicit tool names).
 * The LLM must autonomously decide which tools to invoke.
 *
 * New v0.5.0 inspectors: Security, Health, Scheduler, Error Tracking,
 * WebSocket, plus Redis, Flask routes, SQLAlchemy, Logging, Cache,
 * Outbound HTTP, Metrics.
 *
 * Usage:
 *   1. Start demo: cd demo && LLM_API_KEY=your-key python app.py
 *   2. Run: node scripts/demo-record.js
 */

const BASE_URL = process.env.BASE_URL || 'http://localhost:8000';
const OUTPUT_DIR = './demo-recordings';
const VERSION = 'v01';

// --- Helpers ----------------------------------------------------------------

async function typeMessage(page, text, charDelay = 8) {
  const input = page.locator('#input');
  await input.click();
  await input.pressSequentially(text, { delay: charDelay });
}

async function waitForAgentIdle(page, timeout = 120000) {
  // Wait for send button to be re-enabled
  try {
    await page.waitForFunction(() => {
      const btn = document.querySelector('#send');
      return btn && !btn.disabled;
    }, { timeout });
  } catch {
    console.log('  Warning: Agent still busy, waiting more...');
    await page.waitForFunction(() => {
      const btn = document.querySelector('#send');
      return btn && !btn.disabled;
    }, { timeout: 60000 }).catch(() => {
      console.log('  Warning: Force proceeding after extended wait');
    });
  }

  // Wait for DOM to stabilize (no new messages for 3s)
  let lastCount = 0;
  let stableTime = 0;
  let maxWait = 15000;
  const interval = 1000;
  while (stableTime < 3000 && maxWait > 0) {
    const count = await page.evaluate(() => document.querySelectorAll('.message, .tool-badge').length);
    if (count === lastCount) {
      stableTime += interval;
    } else {
      lastCount = count;
      stableTime = 0;
    }
    await page.waitForTimeout(interval);
    maxWait -= interval;
  }
  await page.waitForTimeout(1500);
}

async function sendAndWait(page, timeout = 120000) {
  await page.locator('#send').click();
  await waitForAgentIdle(page, timeout);
}

async function pause(page, ms = 3000) {
  await page.waitForTimeout(ms);
}

// --- Section 1: Memory (tracemalloc) + GC Stats ────────────────────────────

async function section1_memory_gc(page) {
  console.log('  [1/10] Memory (tracemalloc) + GC Stats');
  await typeMessage(page, "My Flask app feels sluggish under load. Can you check the overall runtime health — Python version, memory usage, and GC statistics?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me detailed tracemalloc statistics — what's using the most memory by file and line number?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Try forcing a garbage collection — I want to see how much memory can be reclaimed and if there are reference cycles.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Threads + Async Tasks + Signals');
}

// --- Section 2: Threads + Async Tasks + Signals ────────────────────────────

async function section2_threads_signals(page) {
  console.log('  [2/10] Threads + Async Tasks + Signals');
  await typeMessage(page, "Show me all the threads running in this process — their names, daemon status, and whether they're alive. Also show thread count.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Is there an asyncio event loop running? If so, show me the event loop details and any pending async tasks.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "What signal handlers are registered? Show me which signals the application is listening for and their handler functions.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Database (SQLAlchemy) + Redis Pool');
}

// --- Section 3: Database (SQLAlchemy) + Redis Pool ─────────────────────────

async function section3_db_redis(page) {
  console.log('  [3/10] Database (SQLAlchemy) + Redis Pool');
  await typeMessage(page, "Are there any SQLAlchemy engines in this application? Show me their connection pool status — active, idle, and checked-out connections.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any slow database queries logged? Show me queries that took more than 100ms with their SQL text.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Check the Redis connection pool — how many connections are active and idle? Show me any Redis operation statistics.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Flask Routes + Jinja2 + Logging Tree');
}

// --- Section 4: Flask Routes + Jinja2 + Logging Tree ───────────────────────

async function section4_routes_logging(page) {
  console.log('  [4/10] Flask Routes + Jinja2 + Logging Tree');
  await typeMessage(page, "What API routes does this Flask app expose? List all the registered endpoints with their methods.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me the Jinja2 template environment — what templates are loaded and what filters are registered?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me the Python logging tree — all configured loggers, their levels, handlers, and formatters.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: HTTP Requests + Cache Stats + Metrics');
}

// --- Section 5: HTTP Requests + Cache Stats + Metrics ──────────────────────

async function section5_http_cache(page) {
  console.log('  [5/10] HTTP Requests + Cache Stats + Metrics');
  await typeMessage(page, "What HTTP requests have come in recently? Show me request statistics — P50, P95, P99 latency and error rate. Also show any slow or error requests.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "What's the cache status? Show me cache hit and miss rates, total keys, and memory usage for any in-memory caches like functools.lru_cache.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me the application metrics — request counts, error rates, latency histograms, and any custom metrics.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Security (auth config, sessions, CORS)');
}

// --- Section 6: Security (auth config, sessions, CORS) ─────────────────────

async function section6_security(page) {
  console.log('  [6/10] Security (auth config, sessions, CORS)');
  await typeMessage(page, "I'm doing a security audit. What authentication and authorization middleware is configured? Show me auth settings and any Flask-Login or JWT configuration.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any active sessions? Show me session details — how many are active and their expiry. Also show me the CORS configuration.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Check for potential security issues — are there any environment variables exposing secrets, insecure configurations, or missing CSRF protection?");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Health Checks + Scheduler');
}

// --- Section 7: Health Checks + Scheduler ──────────────────────────────────

async function section7_health_scheduler(page) {
  console.log('  [7/10] Health Checks + Scheduler');
  await typeMessage(page, "Run a health check on the database connection — is it reachable and responding quickly? Also check the Redis connection health.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any scheduled or background jobs running? Show me the scheduler status and any APScheduler or Celery task queues.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Give me an overall readiness summary — are all critical dependencies healthy and are there any queue backlogs?");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Error Tracking + Warnings');
}

// --- Section 8: Error Tracking + Warnings ──────────────────────────────────

async function section8_errors_warnings(page) {
  console.log('  [8/10] Error Tracking + Warnings');
  await typeMessage(page, "Show me recent errors tracked by the application — any exceptions, tracebacks, or error-level log entries.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any Python warnings captured? Show me recent warnings with their category, message, and source location.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any WebSocket connections active? Show me connection details and any connection-related errors.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Outbound HTTP + FD + FastAPI/OpenAPI');
}

// --- Section 9: Outbound HTTP + FD + FastAPI/OpenAPI ───────────────────────

async function section9_outbound_fastapi(page) {
  console.log('  [9/10] Outbound HTTP + FD + FastAPI/OpenAPI');
  await typeMessage(page, "What outbound HTTP requests has the application made recently? Show me external API calls with response times.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "How many file descriptors are currently open? Is there any risk of hitting the FD limit?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Is this app running as FastAPI or Flask? Show me the OpenAPI schema or route map with response models if available.");
  await sendAndWait(page);
  await pause(page, 5000);
  console.log('  → Transition: Comprehensive Multi-Tool Debugging');
}

// --- Section 10: Comprehensive Multi-Tool Debugging ────────────────────────

async function section10_comprehensive(page) {
  console.log('  [10/10] Comprehensive Multi-Tool Debugging');
  await typeMessage(page, "I'm investigating a production incident. Give me a comprehensive overview: runtime info, memory and GC stats, thread count, recent HTTP requests with errors, database and Redis pool health, and any tracked errors — all in one summary.");
  await sendAndWait(page);
  await pause(page, 6000);

  await typeMessage(page, "Now check: object counts, reference cycles, security settings, scheduler status, and system load. Summarize the app's overall health and flag any concerns.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Main -------------------------------------------------------------------

(async () => {
  console.log(`
+--------------------------------------------------------------+
|  Python Debug Agent v0.5.0 — Demo Recording                  |
|  82 tools / 20 inspectors                                    |
+--------------------------------------------------------------+
  `);

  if (!fs.existsSync(OUTPUT_DIR)) fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  // Verify app is running
  console.log(`Checking app at ${BASE_URL}/agent ...`);
  try {
    const resp = await fetch(`${BASE_URL}/agent/api/tools`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    console.log(`  Found ${data.tools.length} tools registered`);
  } catch (e) {
    console.error(`ERROR: Demo app not running at ${BASE_URL}. Start it first:\n  cd demo && LLM_API_KEY=your-key python app.py`);
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    recordVideo: { dir: OUTPUT_DIR, size: { width: 1280, height: 800 } },
  });
  const page = await context.newPage();

  console.log(`Navigating to ${BASE_URL}/agent ...`);
  await page.goto(`${BASE_URL}/agent`);
  await pause(page, 2000);

  // Pre-generate some HTTP traffic for request tracking demos
  console.log('Generating HTTP traffic for demos...');
  const endpoints = [
    '/api/orders', '/api/orders/1', '/api/health',
    '/api/slow', '/api/error', '/api/orders',
    '/api/orders/2', '/api/health', '/api/compute/50',
  ];
  for (const ep of endpoints) {
    try { await fetch(`${BASE_URL}${ep}`); } catch {}
  }

  // Pre-warm the lru_cache
  try { await fetch(`${BASE_URL}/api/compute/100`); } catch {}

  await pause(page, 1000);

  const sections = [
    { name: '01-memory-gc', fn: section1_memory_gc },
    { name: '02-threads-signals', fn: section2_threads_signals },
    { name: '03-db-redis', fn: section3_db_redis },
    { name: '04-routes-jinja-logging', fn: section4_routes_logging },
    { name: '05-http-cache-metrics', fn: section5_http_cache },
    { name: '06-security', fn: section6_security },
    { name: '07-health-scheduler', fn: section7_health_scheduler },
    { name: '08-errors-warnings', fn: section8_errors_warnings },
    { name: '09-outbound-fd-fastapi', fn: section9_outbound_fastapi },
    { name: '10-comprehensive', fn: section10_comprehensive },
  ];

  const startTime = Date.now();

  for (let i = 0; i < sections.length; i++) {
    const section = sections[i];
    const elapsed = ((Date.now() - startTime) / 60000).toFixed(1);
    console.log(`\n--- [${i + 1}/${sections.length}] ${section.name} (elapsed: ${elapsed} min) ---`);
    await section.fn(page);
    await page.screenshot({ path: `${OUTPUT_DIR}/${VERSION}-demo-${section.name}.png`, fullPage: true });
    console.log(`  Screenshot: ${VERSION}-demo-${section.name}.png`);
  }

  await pause(page, 3000);
  await page.evaluate(() => {
    const container = document.getElementById('chat-container');
    if (container) container.scrollTop = container.scrollHeight;
  });
  await pause(page, 2000);

  const video = page.video();
  const videoPath = await video.path();
  console.log(`\n  Video path: ${videoPath}`);

  await context.close();
  await browser.close();

  // Rename and convert video
  console.log('\n--- Finalizing video ---');
  const finalWebm = `${OUTPUT_DIR}/${VERSION}-full-demo.webm`;
  const finalMp4 = `${OUTPUT_DIR}/${VERSION}-full-demo.mp4`;

  try { fs.unlinkSync(finalWebm); } catch {}
  try { fs.unlinkSync(finalMp4); } catch {}

  if (videoPath && fs.existsSync(videoPath)) {
    fs.copyFileSync(videoPath, finalWebm);
    const size = fs.statSync(finalWebm).size;
    console.log(`  Saved: ${VERSION}-full-demo.webm (${(size / 1024 / 1024).toFixed(1)} MB)`);
  }

  // Convert to mp4
  try {
    console.log('\n--- Converting to mp4 ---');
    if (fs.existsSync(finalWebm)) {
      execSync(`ffmpeg -y -i "${finalWebm}" -c:v libx264 -preset fast -crf 23 -c:a aac "${finalMp4}"`, { stdio: 'pipe' });
      const size = fs.statSync(finalMp4).size;
      console.log(`  Done: ${VERSION}-full-demo.mp4 (${(size / 1024 / 1024).toFixed(1)} MB)`);
    }
  } catch (e) {
    console.log('  (ffmpeg conversion failed, keeping .webm)');
  }

  const totalMin = ((Date.now() - startTime) / 60000).toFixed(1);
  console.log(`
======================================================
  Recording complete!
  Total time: ${totalMin} minutes
  Output: ${OUTPUT_DIR}/${VERSION}-full-demo.mp4
======================================================
  `);
})();
