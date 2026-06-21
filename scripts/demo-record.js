const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');

/**
 * Python Debug Agent v0.1.0 — Full demo recording (~30 tools / 10 inspectors)
 *
 * 7 sections using NATURAL LANGUAGE prompts (no explicit tool names).
 * The LLM must autonomously decide which tools to invoke.
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

// --- Section 1: Python Runtime + Memory + GC --------------------------------
// Tools: get_runtime_info, get_memory_summary, get_gc_stats, trigger_gc,
//        get_tracemalloc_stats, get_process_info, get_disk_usage

async function section1_runtime(page) {
  console.log('  [1/7] Python Runtime + Memory + GC');
  await typeMessage(page, "My Flask app feels sluggish. Can you check the overall runtime health — Python version, memory usage, and GC statistics?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me detailed tracemalloc statistics — what's using the most memory by file and line number?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "What's the process info — PID, CPU time, and are we running in a container? Also check disk space.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Try forcing a garbage collection — I want to see how much memory can be reclaimed and if there are reference cycles.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 2: Threads + Async Tasks --------------------------------------
// Tools: get_thread_info, get_thread_count, get_thread_traceback,
//        get_async_tasks, get_event_loop_info

async function section2_threads_async(page) {
  console.log('  [2/7] Threads + Async Tasks');
  await typeMessage(page, "Show me all the threads running in this process — their names, daemon status, and whether they're alive.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Get the traceback for the main thread — I want to see where it's currently executing.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Is there an asyncio event loop running? If so, show me the event loop details and any pending async tasks.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 3: Modules + Dependencies -------------------------------------
// Tools: get_loaded_modules, get_import_stats, get_module_detail,
//        get_installed_packages, get_python_path

async function section3_modules(page) {
  console.log('  [3/7] Modules + Dependencies');
  await typeMessage(page, "What Python modules are loaded? Show me the import statistics — total count and the largest modules by file size.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me details about the flask module specifically — its version, file path, and public attributes.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "List all installed packages and check the Python module search paths.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 4: Framework + Routes + HTTP Requests --------------------------
// Tools: get_routes, get_middleware, get_recent_requests, get_slow_requests,
//        get_error_requests, get_request_stats

async function section4_http(page) {
  console.log('  [4/7] Framework Routes + HTTP Request Tracking');
  await typeMessage(page, "What API routes does this Flask app expose? List all the registered endpoints.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me the recent HTTP requests that came in. What are the request statistics — P50, P95, P99 latency and error rate?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Are there any slow requests? Show me requests that took more than 100ms. Also show any error requests.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 5: Database + Environment -------------------------------------
// Tools: get_sqlalchemy_engines, get_db_connections,
//        get_environment_variables

async function section5_database(page) {
  console.log('  [5/7] Database + Environment');
  await typeMessage(page, "Are there any SQLAlchemy engines in this application? Show me their connection pool status.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Check database connection pools and active connections if available.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "What environment variables are set? Filter for ones that might contain configuration — but mask any secrets.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 6: Object Counts + Reference Cycles + System --------------------
// Tools: get_object_counts, get_ref_cycles, get_gc_stats,
//        get_system_info

async function section6_objects_system(page) {
  console.log('  [6/7] Object Analysis + System');
  await typeMessage(page, "How many live Python objects are there? Show me the object counts by type — the top 20 types.");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Detect reference cycles in the garbage collector. How many cycles were found and what types are involved?");
  await sendAndWait(page);
  await pause(page, 4000);

  await typeMessage(page, "Show me system information — OS, CPU cores, and load average.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Section 7: Comprehensive Debugging -------------------------------------

async function section7_comprehensive(page) {
  console.log('  [7/7] Comprehensive Debugging Scenario');
  await typeMessage(page, "I'm debugging a performance issue. Give me a comprehensive overview: runtime info, memory and GC stats, thread count, recent HTTP requests with errors, and loaded module count — all in one summary.");
  await sendAndWait(page);
  await pause(page, 6000);

  await typeMessage(page, "Now check: object counts, reference cycles, and system load. Summarize the app's overall health.");
  await sendAndWait(page);
  await pause(page, 5000);
}

// --- Main -------------------------------------------------------------------

(async () => {
  console.log(`
+--------------------------------------------------------------+
|  Python Debug Agent v0.1.0 — Demo Recording                  |
|  ~30 tools / 10 inspectors                                   |
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
    { name: '01-runtime-memory-gc', fn: section1_runtime },
    { name: '02-threads-async', fn: section2_threads_async },
    { name: '03-modules-deps', fn: section3_modules },
    { name: '04-routes-http', fn: section4_http },
    { name: '05-database-env', fn: section5_database },
    { name: '06-objects-system', fn: section6_objects_system },
    { name: '07-comprehensive', fn: section7_comprehensive },
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
