"""Bounded worker processes and real headless resource cleanup."""

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from test_batch import batch


@pytest.mark.parametrize("concurrency", [2, 4])
def test_pool_enforces_global_and_same_domain_limit(tmp_path, concurrency):
    m = batch()
    script = tmp_path / "worker.py"
    script.write_text("""import sys,json,time
from pathlib import Path
j=json.loads(Path(sys.argv[1]).read_text())
with open(j['events'],'a') as f:f.write(json.dumps({'event':'start','domain':j['domain']})+'\\n')
time.sleep(.12)
with open(j['events'],'a') as f:f.write(json.dumps({'event':'end','domain':j['domain']})+'\\n')
Path(j['result_path']).write_text(json.dumps({'outcome':'READY_TO_SUBMIT','backlink_id':j['backlink_id']}))
""")
    events = tmp_path / "events"
    jobs = [
        {"backlink_id": str(i), "domain": "a.example" if i in {0, 4, 5} else str(i) + ".example", "events": str(events)}
        for i in range(8)
    ]
    result = asyncio.run(
        m.run_pool(jobs, runtime=tmp_path, concurrency=concurrency, timeout=3, command=[sys.executable, str(script)])
    )
    active = 0
    maximum = 0
    domains = set()
    for entry in map(json.loads, events.read_text().splitlines()):
        if entry["event"] == "start":
            assert entry["domain"] not in domains
            domains.add(entry["domain"])
            active += 1
            maximum = max(maximum, active)
        else:
            domains.remove(entry["domain"])
            active -= 1
    assert active == 0 and maximum == concurrency
    assert [x["backlink_id"] for x in result] == [str(i) for i in range(8)]
    with pytest.raises(ValueError):
        asyncio.run(m.run_pool([], runtime=tmp_path, concurrency=5))


@pytest.mark.parametrize("crash", [False, True])
def test_timeout_or_crash_kills_worker_browser_descendants(tmp_path, crash):
    m = batch()
    script = tmp_path / "worker.py"
    script.write_text("""import json,sys,subprocess,time,os
from pathlib import Path
j=json.loads(Path(sys.argv[1]).read_text())
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
Path(j['pidfile']).write_text(str(p.pid))
if j['crash']:os._exit(2)
time.sleep(30)
""")
    job = {"backlink_id": "a", "domain": "a.example", "pidfile": str(tmp_path / "pid"), "crash": crash}
    result = asyncio.run(m.run_pool([job], runtime=tmp_path, timeout=0.4, command=[sys.executable, str(script)]))
    assert result[0]["outcome"] == "TEMPORARILY_UNAVAILABLE"
    pid = int((tmp_path / "pid").read_text())
    import subprocess

    check = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    assert not check.stdout.strip() or check.stdout.strip().startswith("Z")


def test_real_browser_human_and_crash_close_all_resources(tmp_path):
    assert importlib.util.find_spec("backlink_submitter.batch_worker") is not None, "Site worker missing"
    from playwright.async_api import async_playwright

    from backlink_submitter.batch_worker import inspect_page, site_context

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            async with site_context(pw, tmp_path / "human-profile", browser=browser) as ctx:
                page = await ctx.new_page()
                await page.set_content("<h1>Verify you are human</h1>")
                result = await inspect_page(page, {}, None)
                assert result["outcome"] == "HUMAN_VERIFICATION_REQUIRED"
            assert browser.contexts == []
            with pytest.raises(RuntimeError):
                async with site_context(pw, tmp_path / "crash-profile", browser=browser) as ctx:
                    await ctx.new_page()
                    raise RuntimeError("fixture crash")
            assert browser.contexts == []
            await browser.close()

    asyncio.run(run())


def test_fatal_worker_exit_reclaims_actual_chrome(tmp_path):
    m = batch()
    script = tmp_path / "chrome_worker.py"
    script.write_text("""import asyncio,json,os,sys,subprocess
from pathlib import Path
from playwright.async_api import async_playwright
async def run():
 j=json.loads(Path(sys.argv[1]).read_text())
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='chrome',headless=True)
  ctx=await browser.new_context();await ctx.new_page()
  rows=subprocess.check_output(['ps','-axo','pid=,ppid=']).decode().splitlines()
  pairs=[tuple(map(int,r.split())) for r in rows if len(r.split())==2]
  owned={os.getpid()}
  for _ in range(10):owned|={pid for pid,parent in pairs if parent in owned}
  Path(j['pidfile']).write_text(json.dumps(sorted(owned-{os.getpid()})))
  os._exit(2)
asyncio.run(run())
""")
    job = {"backlink_id": "chrome", "domain": "chrome.example", "pidfile": str(tmp_path / "chrome-pids")}
    result = asyncio.run(m.run_pool([job], runtime=tmp_path, timeout=4, command=[sys.executable, str(script)]))
    assert result[0]["outcome"] == "TEMPORARILY_UNAVAILABLE"
    import subprocess
    import time

    pids = json.loads((tmp_path / "chrome-pids").read_text())
    time.sleep(0.3)
    live = []
    for pid in pids:
        r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        if r.stdout.strip() and not r.stdout.strip().startswith("Z"):
            live.append(pid)
    try:
        assert live == [], "Worker-owned real Chrome processes leaked"
    finally:
        import signal

        for pid in live:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_explicit_headed_handoff_opens_only_selected_station_and_blocks_submit(tmp_path):
    from types import SimpleNamespace

    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import handoff

    visits = []
    flags = []
    aborted = []

    class Context:
        async def route(self, pattern, handler):
            self.handler = handler

        def on(self, event, callback):
            self.closed = callback

        async def new_page(self):
            return self

        async def goto(self, url, **kw):
            visits.append(url)

            class Route:
                request = SimpleNamespace(method="POST", url="https://startupfound.com/api/startups/submit")

                async def abort(self):
                    aborted.append(True)

                async def continue_(self):
                    raise AssertionError("Final dispatch must be blocked")

            await self.handler(Route())
            self.closed(self)

        async def close(self):
            pass

    class Chromium:
        async def launch_persistent_context(self, path, **kw):
            flags.append(kw["headless"])
            return Context()

    api = SheetAPI()
    api.row[:3] = ["wyrplay", "startupfound.com", "startupfound.com"]
    api.row[3] = "需人工核查"
    job = {
        "resume": True,
        "owner_human_action": True,
        "backlink_id": "startupfound.com",
        "domain": "startupfound.com",
        "submit_url": "https://startupfound.com/submit",
        "runtime_root": str(tmp_path),
        "row": 2,
    }
    result = asyncio.run(handoff(job, api, SimpleNamespace(chromium=Chromium())))
    assert visits == ["https://startupfound.com/submit"] and flags == [False] and aborted == [True]
    assert result["submit"] == 0 and api.writes == 0


def test_site_human_stop_closes_context_before_queue_and_live_manual_write(tmp_path):
    from shutil import copytree
    from types import SimpleNamespace

    from playwright.async_api import async_playwright
    from test_contracts import SheetAPI

    from backlink_submitter.batch_worker import run_site
    from backlink_submitter.contracts import load_project

    root = tmp_path / "pack"
    copytree(Path(__file__).resolve().parents[1] / "projects/wyrplay", root)
    adapter = {
        "domain": "site.example",
        "submit_url": "https://site.example/submit",
        "fields": {"Product / App Name": "#name", "Website URL": "#url"},
        "required_fields": ["Product / App Name", "Website URL"],
        "final_submit_selector": "#submit",
        "final_submit_text": "Submit product",
        "free_verified": True,
        "qualification": "QUALIFIED_A",
        "final_action_verified": True,
        "login_required": False,
        "submission_request": {"verified": True, "method": "POST", "host": "site.example", "path": "/api/submit"},
    }
    (root / "adapters/site.example.json").write_text(json.dumps(adapter))
    pack = load_project("wyrplay", root)
    api = SheetAPI()
    job = {
        "project_id": "wyrplay",
        "mode": "live",
        "runtime_root": str(tmp_path),
        "domain": "site.example",
        "backlink_id": "site.example",
        "row": 2,
        "submit_url": "https://site.example/submit",
    }

    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)

            class Chromium:
                async def launch_persistent_context(self, profile, **kw):
                    assert kw["headless"] is True
                    ctx = await browser.new_context(service_workers="block")
                    await ctx.route(
                        "https://site.example/**",
                        lambda r: r.fulfill(status=200, content_type="text/html", body="<h1>Verify you are human</h1>"),
                    )
                    return ctx

            result = await run_site(job, pack, api, SimpleNamespace(chromium=Chromium()))
            assert result["outcome"] == "HUMAN_VERIFICATION_REQUIRED"
            assert browser.contexts == []
            assert (tmp_path / "human-queue/site.example.json").is_file()
            assert api.row[3] == "需人工核查" and api.row[4] == "" and api.writes == 1
            assert not (tmp_path / "submit-intents/wyrplay/site.example.json").exists()
            await browser.close()

    asyncio.run(run())
