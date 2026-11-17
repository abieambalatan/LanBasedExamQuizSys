r"""Exercise real HTTP bursts against Waitress using ONLY a temporary database.

Run: .venv\Scripts\python.exe load_test.py --users 200 --output reports\load_test_results.json
No requests go to the live portal and no real student data is read or changed.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.cookies import SimpleCookie
import importlib.metadata
import json
import logging
import multiprocessing
import os
from pathlib import Path
import platform
import statistics
import tempfile
import threading
import time


def test_server(db_path, pipe):
    os.environ["DJANGO_SETTINGS_MODULE"] = "exam_portal.test_settings"
    os.environ["EXAM_PORTAL_ADMIN_PASSWORD"] = "synthetic-load-test-only"
    os.environ["EXAM_PORTAL_DB_PATH"] = db_path
    from app import server_options
    from exam_portal.wsgi import application
    from waitress import create_server

    # A synchronized burst deliberately queues work. Keep other errors visible.
    logging.getLogger("waitress.queue").setLevel(logging.ERROR)
    options = server_options()
    options.update(host="127.0.0.1", port=0)
    server = create_server(application, **options)
    pipe.send(int(server.effective_port))
    pipe.close()
    server.run()


def seed_database(db_path, users, question_count):
    os.environ["DJANGO_SETTINGS_MODULE"] = "exam_portal.test_settings"
    os.environ["EXAM_PORTAL_ADMIN_PASSWORD"] = "synthetic-load-test-only"
    os.environ["EXAM_PORTAL_DB_PATH"] = db_path
    import django
    django.setup()
    from portal import db as portal
    from portal.security import generate_password_hash

    from django.core.management import call_command
    call_command("migrate", interactive=False, verbosity=0)
    password_hash = generate_password_hash("load-test-password")
    conn = portal.get_db()
    try:
        conn.execute(
            "INSERT INTO teachers (id,name,username,department,password_hash,created_at) VALUES (?,?,?,?,?,?)",
            ("test-teacher", "Synthetic Teacher", "load-teacher", "BSIT", password_hash, "2026-01-01"),
        )
        conn.execute("INSERT INTO teacher_departments VALUES (?,?)", ("load-teacher", "BSIT"))
        for i in range(users):
            student_id, roll_no = f"test-student-{i}", f"LOAD-{i:04d}"
            conn.execute(
                """INSERT INTO students (id,name,roll_no,department,username,password_hash,
                   teacher_username,section,year_level,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (student_id, f"Synthetic Student {i}", roll_no, "BSIT", roll_no,
                 password_hash, "", "A", "1st Year", "2026-01-01"),
            )
        conn.execute(
            """INSERT INTO exams (id,title,duration,department,created_by,year_level,subject,
               section_scope,activity_type,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("load-exam", "Synthetic 50-question Exam", 60, "BSIT", "load-teacher",
             "1st Year", "Load Test", "ALL", "exam", "2026-01-01"),
        )
        conn.execute("INSERT INTO exam_departments VALUES (?,?)", ("load-exam", "BSIT"))
        for i in range(question_count):
            question_type = ("multiple_choice", "identification", "true_false", "matching")[i % 4]
            options = ["Displays images", "Produces printed copies", "Stores files", "Records sound", "Processes instructions"] if question_type == "matching" else []
            correct = 4 if question_type == "matching" else 0 if question_type == "true_false" else 1
            conn.execute(
                """INSERT INTO questions (id,exam_id,position,part,type,text,option_a,option_b,
                   option_c,option_d,correct,answer_text,alternatives_json,options_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"load-q-{i}", "load-exam", i, i % 4 + 1, question_type,
                 f"Synthetic question {i + 1}", "A", "B", "C", "D", correct,
                 "MANILA" if question_type == "identification" else "", "[]", json.dumps(options)),
            )
        conn.commit()
    finally:
        conn.close()
    from django.db import connections
    connections.close_all()
    return portal, password_hash.split("$", 1)[0]


class Student:
    def __init__(self, index, port):
        self.index = index
        self.connection = http.client.HTTPConnection("127.0.0.1", port, timeout=90)
        self.cookies = {}
        self.csrf_token = None
        self.result_id = None

    def request(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if method not in ("GET", "HEAD", "OPTIONS"):
            if not self.csrf_token:
                self.csrf_token = self.request("GET", "/api/csrf")["csrfToken"]
            headers["X-CSRFToken"] = self.csrf_token
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        self.connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = self.connection.getresponse()
        content = response.read()
        for key, value in response.getheaders():
            if key.lower() == "set-cookie":
                cookie = SimpleCookie()
                cookie.load(value)
                self.cookies.update({name: morsel.value for name, morsel in cookie.items()})
        if response.status != 200:
            raise AssertionError(f"HTTP {response.status}: {content[:180]!r}")
        if path.endswith("/login") or path == "/api/logout":
            self.csrf_token = None
        return json.loads(content)

    def login(self):
        result = self.request("POST", "/api/students/login", {
            "idNumber": f"LOAD-{self.index:04d}", "password": "load-test-password",
        })
        assert result["rollNo"] == f"LOAD-{self.index:04d}", "Wrong student session"

    def open_exam(self, question_count):
        exams = self.request("GET", "/api/exams?studentView=1")
        assert any(exam["id"] == "load-exam" for exam in exams), "Exam missing from dashboard"
        self.request("GET", "/api/results")
        exam = self.request("GET", "/api/exams/load-exam/take")
        assert len(exam["questions"]) == question_count, "Missing questions"
        assert not any("correct" in q or "answerText" in q for q in exam["questions"]), "Answer leak"

    def submit(self, question_count, replay=False):
        result = self.request("POST", "/api/results", {
            "examId": "load-exam", "submissionId": f"load-attempt-{self.index}",
            "answers": {f"load-q-{i}": (1, "Manila", 0, 4)[i % 4] for i in range(question_count)},
            "timeTakenSec": 60, "autoSubmitted": True, "submitReason": "time_limit",
        })
        assert result["rollNo"] == f"LOAD-{self.index:04d}", "Result belongs to another student"
        assert result["score"] == result["total"] == sum(2 if i % 4 < 2 else 1 for i in range(question_count)), "Incorrect score"
        assert not {"review", "answers", "questions", "correct", "answers_json"}.intersection(result), "Submission receipt exposed answer details"
        if replay:
            assert result["id"] == self.result_id, "Retry created a second result"
        self.result_id = result["id"]


def burst(name, students, action):
    barrier = threading.Barrier(len(students) + 1, timeout=30)

    def run(student):
        barrier.wait()
        started = time.perf_counter()
        try:
            action(student)
            error = None
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        return time.perf_counter() - started, error

    with ThreadPoolExecutor(max_workers=len(students)) as pool:
        futures = [pool.submit(run, student) for student in students]
        started = time.perf_counter()
        barrier.wait()
        results = [future.result() for future in futures]
    durations = sorted(elapsed for elapsed, _ in results)
    errors = [error for _, error in results if error]
    report = {
        "phase": name, "requests_started_together": len(students),
        "passed": len(students) - len(errors), "failed": len(errors),
        "total_seconds": round(time.perf_counter() - started, 3),
        "p50_seconds": round(statistics.median(durations), 3),
        "p95_seconds": round(durations[max(0, (95 * len(durations) + 99) // 100 - 1)], 3),
        "max_seconds": round(max(durations), 3), "errors": errors[:5],
    }
    print(json.dumps(report), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--questions", type=int, default=50)
    parser.add_argument("--output", type=Path, default=Path("reports") / "load_test_results.json")
    args = parser.parse_args()
    if not 1 <= args.users <= 250 or not 1 <= args.questions <= 500:
        parser.error("Use 1-250 users and 1-500 questions.")
    protected = Path(__file__).parent / "exam.db"
    if args.output.resolve() == protected.resolve() or args.output.suffix.lower() != ".json":
        parser.error("The output must be a JSON report, separate from exam.db.")
    production_hash_before = hashlib.sha256(protected.read_bytes()).hexdigest()
    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "Loopback HTTP, synthetic data, separate Waitress process; excludes physical LAN/Wi-Fi.",
        "users": args.users, "questions": args.questions,
        "question_types": ["multiple_choice", "identification", "true_false", "matching"],
        "python": platform.python_version(), "os": platform.system(), "logical_cpus": os.cpu_count(),
        "waitress": importlib.metadata.version("waitress"),
        "django": importlib.metadata.version("Django"),
        "app_sha256": hashlib.sha256(b"".join(path.read_bytes() for path in [Path("app.py"), *sorted(Path("portal").glob("*.py")), *sorted(Path("exam_portal").glob("*.py"))])).hexdigest(),
    }
    with tempfile.TemporaryDirectory(prefix="aralhub-load-") as temporary:
        portal, hash_method = seed_database(os.path.join(temporary, "synthetic.db"), args.users, args.questions)
        from app import server_options
        report.update(password_hash_method=hash_method, server=server_options())
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=test_server, args=(os.path.join(temporary, "synthetic.db"), sender))
        students = []
        try:
            process.start()
            sender.close()
            if not receiver.poll(20):
                raise RuntimeError("Test server did not start within 20 seconds")
            port = receiver.recv()
            students = [Student(i, port) for i in range(args.users)]
            phases = []
            phases.append(burst("login", students, lambda student: student.login()))
            phases.append(burst("dashboard_and_open_exam", students, lambda student: student.open_exam(args.questions)))
            phases.append(burst("simultaneous_auto_submit", students, lambda student: student.submit(args.questions)))
            phases.append(burst("retry_saved_submission", students, lambda student: student.submit(args.questions, replay=True)))
            report["phases"] = phases
            conn = portal.get_db()
            try:
                report["saved_results"] = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
                report["correct_results"] = conn.execute(
                    "SELECT COUNT(*) FROM results WHERE score=? AND total=?", (sum(2 if i % 4 < 2 else 1 for i in range(args.questions)), sum(2 if i % 4 < 2 else 1 for i in range(args.questions)))
                ).fetchone()[0]
                report["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
                report["database_integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
        finally:
            for student in students:
                student.connection.close()
            if process.pid:
                process.terminate()
                process.join(timeout=10)
            receiver.close()
    report["production_database_unchanged"] = production_hash_before == hashlib.sha256(protected.read_bytes()).hexdigest()
    report["passed"] = (
        all(phase["failed"] == 0 and phase["max_seconds"] < 30 for phase in report["phases"])
        and report["saved_results"] == report["correct_results"] == args.users
        and report["database_integrity"] == "ok" and report["production_database_unchanged"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: report saved to {args.output}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
