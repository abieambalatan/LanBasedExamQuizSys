"""Exercise browser -> Waitress -> database -> teacher monitoring on isolated data."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import nullcontext

import test_app as fixtures


class LiveMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
        if not cls.edge.exists():
            raise unittest.SkipTest("Microsoft Edge is not installed")
        try:
            import websocket
        except ImportError:
            raise unittest.SkipTest("Install requirements-dev.txt for browser integration checks")
        fixtures.ExamPortalTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.ExamPortalTests.tearDownClass()

    def test_live_counts_offline_recovery_resume_and_teacher_timeline(self):
        import websocket
        from django.core.handlers.wsgi import WSGIHandler
        from django.conf import settings
        from waitress import create_server

        fixture = fixtures.ExamPortalTests()
        fixture.setUp()
        server = process = connection = None
        try:
            clients, payload = fixture.submission_fixture()
            teacher = fixtures.APIClient()
            teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
            server = create_server(WSGIHandler(), host="127.0.0.1", port=0, threads=4)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            origin = f"http://127.0.0.1:{server.effective_port}"
            activity_url = f"/api/exams/{payload['examId']}/activity"
            profile_directory = tempfile.TemporaryDirectory(prefix="aralhub-live-monitor-")
            self.addCleanup(profile_directory.cleanup)
            with nullcontext(profile_directory.name) as profile:
                process = subprocess.Popen([
                    str(self.edge), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                    "--disable-background-networking", f"--user-data-dir={profile}", "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1", "--remote-allow-origins=*", "about:blank",
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                active_port = Path(profile) / "DevToolsActivePort"
                deadline = time.monotonic() + 15
                while not active_port.exists():
                    if time.monotonic() > deadline or process.poll() is not None:
                        self.fail("Integration browser did not start")
                    time.sleep(.1)
                port = int(active_port.read_text().splitlines()[0])
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                    target = next(item for item in json.load(response) if item["type"] == "page")
                connection = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=15)
                sequence = 0

                def command(method, params=None):
                    nonlocal sequence
                    sequence += 1
                    connection.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
                    while True:
                        result = json.loads(connection.recv())
                        if result.get("id") == sequence:
                            self.assertNotIn("error", result)
                            return result.get("result", {})

                def evaluate(expression):
                    result = command("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
                    self.assertNotIn("exceptionDetails", result, str(result.get("exceptionDetails")))
                    return result.get("result", {}).get("value")

                def wait_for(expression):
                    deadline = time.monotonic() + 10
                    while not evaluate(expression):
                        if time.monotonic() > deadline:
                            self.fail("Browser did not reach expected state: " + expression)
                        time.sleep(.1)

                command("Page.enable")
                command("Network.enable")
                command("Emulation.setFocusEmulationEnabled", {"enabled": True})
                for role, client in (("student", clients[0]), ("teacher", teacher)):
                    command("Network.setCookie", {"name": settings.SESSION_COOKIE_NAME + "_" + role,
                            "value": client.cookies[settings.SESSION_COOKIE_NAME].value, "url": origin, "httpOnly": True})
                command("Page.navigate", {"url": origin + "/student"})
                wait_for("typeof state !== 'undefined' && state.view === 'studentHome' && state.exams.length > 0")
                evaluate("(async()=>{await beginExam(" + json.dumps(payload["examId"]) + ");await syncAssessmentActivity();return true;})()")
                self.assertEqual(fixtures.Result.objects.count(), 0)
                self.assertEqual(len(teacher.get(activity_url).json()), 1)
                evaluate("window.testHidden=false;window.testFocused=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>testHidden});document.hasFocus=()=>testFocused")
                for departure in range(2):
                    if departure == 1:
                        command("Network.emulateNetworkConditions", {"offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
                    evaluate("(async()=>{testFocused=false;window.dispatchEvent(new Event('blur'));testHidden=true;document.dispatchEvent(new Event('visibilitychange'));await syncAssessmentActivity();await syncAssessmentActivity();return true;})()")
                    if departure == 1:
                        self.assertTrue(evaluate("!!state.runtime.activitySyncError"), str(evaluate("({error:state.runtime.activitySyncError,synced:state.runtime.activitySyncedCount,events:state.runtime.activityLog.events.length,pending:!!state.runtime.activitySyncRequest})")))
                        self.assertEqual(evaluate("readSavedAttempt().activityLog.events.filter(e=>e.type==='page_hidden').length"), 2)
                        command("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
                    evaluate("(async()=>{testHidden=false;testFocused=true;document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'));acknowledgeAssessmentFocus();state.runtime.nextActivitySyncAt=0;await syncAssessmentActivity();await syncAssessmentActivity();return true;})()")
                detail = teacher.get(activity_url).json()[0]
                self.assertEqual(detail["activitySummary"]["focusLossCount"], 2)
                self.assertEqual(detail["activitySummary"]["hiddenCount"], 2)
                self.assertEqual(fixtures.Result.objects.count(), 0)
                command("Page.navigate", {"url": origin + "/teacher"})
                wait_for("typeof state !== 'undefined' && state.view === 'adminHome'")
                evaluate("(async()=>{await openAdminResults(" + json.dumps(payload["examId"]) + ");return true;})()")
                self.assertEqual(evaluate("document.querySelectorAll('.activity-monitor-table tbody tr').length"), 1)
                self.assertEqual(evaluate("state.activityAttempts[0].activitySummary.hiddenCount"), 2)
                evaluate("(async()=>{await openActivityLog(state.activityAttempts[0].id);return true;})()")
                self.assertTrue(evaluate("document.getElementById('activityDetailPanel').textContent.includes('Exam page became hidden')"))
                command("Page.navigate", {"url": origin + "/student"})
                wait_for("typeof state !== 'undefined' && state.view === 'studentHome' && !!state.savedAttempt")
                expected = evaluate("(async()=>{await resumeSavedAttempt(" + json.dumps(payload["examId"]) + ");await syncAssessmentActivity();const events=state.runtime.activityLog.events;const counts={focus:events.filter(e=>e.type==='focus_lost').length,hidden:events.filter(e=>e.type==='page_hidden').length};await submitExam(false);return counts;})()")
                self.assertEqual(evaluate("state.view"), "studentResult")
                result = fixtures.Result.objects.get()
                receipt = teacher.get(f"/api/results/{result.id}/review").json()
                self.assertGreaterEqual(expected["focus"], 2)
                self.assertGreaterEqual(expected["hidden"], 2)
                self.assertEqual(receipt["activitySummary"]["focusLossCount"], expected["focus"])
                self.assertEqual(receipt["activitySummary"]["hiddenCount"], expected["hidden"])
                self.assertEqual(teacher.get(activity_url).json()[0]["status"], "submitted")
                connection.close()
                connection = None
                process.terminate()
                process.wait(timeout=10)
                process = None
        finally:
            if connection:
                connection.close()
            if process:
                process.terminate()
                process.wait(timeout=10)
            if server:
                server.task_dispatcher.shutdown()
                server.close()
                thread.join(timeout=3)
            fixture.tearDown()
