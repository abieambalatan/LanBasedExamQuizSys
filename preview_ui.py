"""Capture the real interface with synthetic preview data, without starting the portal."""

import json
import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parent


def preview_source(screen):
    if screen == "superadmin":
        return native_admin_preview()
    teacher = screen in ("teacher", "admin", "builder", "results", "staff-login", "staff-signup", "review", "teacher-materials", "notifications")
    shared_login = screen in ("login", "staff-login")
    filename = "login.html" if shared_login else "administrator.html" if teacher else "index.html"
    source = (ROOT / "files" / filename).read_text(encoding="utf-8")
    helpers = (ROOT / "files/js/common.js").read_text(encoding="utf-8")
    helpers += "\n" + (ROOT / "files/js/learning.js").read_text(encoding="utf-8")
    if teacher:
        helpers += "\n" + (ROOT / "files/js/notifications.js").read_text(encoding="utf-8")
    parser = (ROOT / "files/js/exam-format.js").read_text(encoding="utf-8") if teacher else ""
    script = re.findall(r"<script>(.*?)</script>", source, re.S)[-1]
    activities = [
        {"id": "sample-1", "title": "Introduction to Programming", "subject": "Computer Programming 1", "activityType": "exam", "duration": 60, "questionCount": 40, "attempts": 24, "department": "BSIT", "departments": ["BSIT"], "yearLevel": "1st Year", "sectionScope": "ALL"},
        {"id": "sample-2", "title": "The Fundamentals of Computing", "subject": "Computing Fundamentals", "activityType": "quiz", "duration": 20, "questionCount": 15, "attempts": 18, "department": "BSIT", "departments": ["BSIT"], "yearLevel": "1st Year", "sectionScope": "A"},
        {"id": "sample-3", "title": "Understanding Digital Systems", "subject": "Computer Systems", "activityType": "exam", "duration": 45, "questionCount": 30, "attempts": 12, "department": "BSIT", "departments": ["BSIT"], "yearLevel": "1st Year", "sectionScope": "ALL"},
    ]
    setup = ""
    if shared_login:
        setup = ""
    elif screen == "signup":
        setup = "setView('studentSignup');"
    elif screen == "staff-signup":
        setup = "setView('teacherSignup');"
    elif screen != "landing":
        role = "admin" if screen == "admin" else "teacher" if teacher else "student"
        setup = f"state.currentUser = {json.dumps({'role': role, 'name': 'Alex Santos', 'department': 'BSIT', 'departments': ['BSIT'], 'section': 'A', 'yearLevel': '1st Year', 'rollNo': 'PREVIEW-001'})};\n"
        setup += f"state.exams = {json.dumps(activities)};\n"
        if teacher:
            setup += "syncSubmissionNotificationUpdates=()=>{};state.notificationUnread=2;\n"
            setup += "state.students = Array.from({length: 36}, (_, i) => ({id: 'preview-' + i, name: 'Sample Student ' + (i + 1), roll_no: 'PREVIEW-' + (i + 1), department: 'BSIT', section: 'A', year_level: '1st Year'}));\n"
            setup += "state.teachers = [{id:'t1',name:'Alex Santos',username:'alex.santos',department:'BSIT',exam_count:3,attempt_count:54}];\n"
            setup += "setView('adminHome');\n"
            if screen == "builder":
                setup += "startCreateExam(); state.draft.title = 'Fundamentals of Computing'; state.draft.subject = 'Computing 1'; state.draft.questions = parseExamText(" + json.dumps((ROOT / "files/exam_template.txt").read_text(encoding="utf-8")) + ").map((q,i) => ({...q,id:'preview-q-'+i})); state.draft.expandedQuestionId='preview-q-4'; render();\n"
            elif screen == "results":
                setup += "state.adminResultsExamId='sample-1'; state.currentExamResults=Array.from({length:8},(_,i)=>({id:'r'+i,name:'Student, Sample '+(i+1),rollNo:'PREVIEW-'+(i+1),department:'BSIT',section:'A',score:35-i,total:40,timeTakenSec:1200+i*75,submittedAt:'2026-10-19T08:00:00'})); setView('adminResults');\n"
            elif screen == "review":
                setup += "state.adminReviewResult={id:'r1',examId:'sample-1',examTitle:'Introduction to Programming',activityType:'exam',name:'Student, Sample A.',rollNo:'PREVIEW-001',department:'BSIT',score:1,total:2,timeTakenSec:720,review:[{text:'A program is a sequence of instructions.',type:'true_false',options:['True','False'],chosen:0,correct:0,isCorrect:true},{text:'Name the component that processes instructions.',type:'identification',options:[],chosen:'MONITOR',answer:'CPU',isCorrect:false}]}; setView('adminResultReview');\n"
            elif screen == "notifications":
                setup += "state.notificationItems=[{id:'n1',studentName:'Dela Cruz, Juan P.',rollNo:'STUDENT-001',activityTitle:'Introduction to Programming activity',subject:'Computer Programming 1',createdAt:'2026-11-11T13:15:00+08:00',isRead:false,isReplacement:false,materialId:'lecture1',submissionId:'s1'},{id:'n2',studentName:'Santos, Maria A.',rollNo:'STUDENT-002',activityTitle:'Week 1 exercises',subject:'Computer Programming 1',createdAt:'2026-11-11T13:10:00+08:00',isRead:false,isReplacement:true,materialId:'lecture1',submissionId:'s2'},{id:'n3',studentName:'Reyes, Carlo B.',rollNo:'STUDENT-003',activityTitle:'Digital systems worksheet',subject:'Computing Fundamentals',createdAt:'2026-11-11T12:45:00+08:00',isRead:true,isReplacement:false,materialId:'lecture2',submissionId:'s3'}];state.workspaceSection='notifications';state.view='teacherNotifications';render();\n"
        else:
            setup += "state.myResults=[{id:'r1',examId:'sample-3',score:26,total:30,percent:86.7}]; setView('studentHome');\n"
            if screen in ("assessment", "focus-warning"):
                setup += "state.runtime={exam:{title:'Introduction to Programming',subject:'Computer Programming 1',yearLevel:'1st Year',sectionScope:'ALL',duration:60,activityType:'exam',questions:[{id:'q1',part:3,type:'true_false',text:'A computer program is a sequence of instructions that tells a computer what to do.',options:['True','False']},{id:'q2',part:4,type:'matching',text:'CPU',options:['Displays images','Produces printed copies','Stores files','Processes instructions']}]},answers:{},secondsLeft:3280,currentIdx:0}; setView('takeExam');\n"
                if screen == "focus-warning":
                    setup += "state.runtime.focusDeadlineAt=Date.now()+10000;render();\n"
            elif screen == "receipt":
                setup += "state.lastResult={examTitle:'Introduction to Programming',score:35,total:40,timeTakenSec:1200}; setView('studentResult');\n"
    if screen in ("teacher-materials", "student-materials"):
        materials = [{
            "id": "lecture1", "title": "Introduction to Programming", "subject": "Computer Programming 1",
            "teacherName": "Alex Santos", "instructions": "Read the lecture slides. Complete the exercises on the last page and upload your answers below.",
            "createdAt": "2026-11-11T08:00:00+08:00", "filename": "Week 1 - Introduction to Programming.pptx", "size": 2516582,
            "openUrl": "#", "downloadUrl": "#", "requiresSubmission": True, "submissionCount": 2,
            "targetClasses": [{"department": "BSIT", "yearLevel": "1st Year", "section": "A"}],
            "mySubmission": {"id": "s1", "filename": "Completed Activity - Student Answers.docx", "size": 34800, "submittedAt": "2026-11-11T09:00:00+08:00", "openUrl": "#", "downloadUrl": "#"},
        }]
        setup += "state.learningMaterials=" + json.dumps(materials) + ";state.workspaceSection='materials';state.view='learningHome';render();\n"
        if teacher:
            setup += "document.querySelector('.learning-upload').open=true;\n"
            setup += "for (const [department, yearIndex, section] of [['BSIT',0,'A'],['BSCRIM',1,'B']]) { const di=DEPARTMENTS.indexOf(department); const group=document.getElementById('lecture-department-'+di); document.querySelector('[name=lectureDepartment][value='+department+']').checked=true; toggleLearningDepartment(di,true); group.querySelectorAll('[name=lectureYear]')[yearIndex].checked=true; toggleLearningYear(di,yearIndex,true); const input=document.getElementById('lecture-year-'+di+'-'+yearIndex).querySelector('[name=lectureClass][value='+section+']'); if(input) input.checked=true; } updateLearningClassCount();\n"
    check = """
setTimeout(() => {
  const check = document.createElement('meta'); check.id='uiLayoutCheck';
  check.content=JSON.stringify({width:innerWidth,documentWidth:document.documentElement.scrollWidth,view:state.view,overflow:document.documentElement.scrollWidth>innerWidth+1});
  document.head.append(check);
}, 100);
"""
    return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="' + (ROOT / "files").as_uri() + '/"><link rel="stylesheet" href="css/style.css"></head><body><a class="skip-link" href="#mainContent">Skip to content</a><div id="app"></div><script>' + helpers + "\n" + parser + "\n" + script + "\n" + setup + "\n" + check + "</script></body></html>"


def native_admin_preview():
    """Render the actual Django console using a disposable, synthetic database."""
    from django.contrib.staticfiles import finders
    from test_app import ExamPortalTests
    ExamPortalTests.setUpClass()
    fixture = ExamPortalTests()
    fixture.setUp()
    try:
        students, payload = fixture.submission_fixture()
        students[0].post("/api/results", json=payload)
        source = fixture.native_admin_client().get("/admin/").content.decode()
    finally:
        fixture.tearDown()
        ExamPortalTests.tearDownClass()
    source = re.sub(r'(["\'])/static/([^"\']+)', lambda match: match[1] + Path(finders.find(match[2].split("?", 1)[0])).as_uri(), source)
    # Preview snapshots remain static and never request the live school server.
    source = re.sub(r'<script[^>]+aralhub-dashboard\.js[^>]*></script>', '', source)
    source = source.replace('</head>', '''<meta id="uiLayoutCheck" content="">
<script>addEventListener('load',()=>{document.getElementById('uiLayoutCheck').content=JSON.stringify({width:innerWidth,documentWidth:document.documentElement.scrollWidth,view:'superadmin',overflow:document.documentElement.scrollWidth>innerWidth+1,headerOverflow:document.getElementById('user-tools').getBoundingClientRect().bottom>document.getElementById('header').getBoundingClientRect().bottom});});</script></head>''')
    return source


def main():
    import websocket
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--screens", nargs="+")
    args = parser.parse_args()

    edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
    output = ROOT / "ui-previews"
    output.mkdir(exist_ok=True)
    cases = [
        ("notifications", 1440, 1100), ("notifications", 768, 1100), ("notifications", 390, 1100), ("notifications", 320, 1100),
        ("login", 320, 1000), ("login", 768, 1100),
        ("teacher-materials", 1440, 1100), ("teacher-materials", 768, 1100), ("teacher-materials", 390, 1100), ("teacher-materials", 320, 1100),
        ("student-materials", 1440, 1100), ("student-materials", 768, 1100), ("student-materials", 390, 1100), ("student-materials", 320, 1100),
        ("superadmin", 1440, 1100), ("superadmin", 390, 1000),
        ("focus-warning", 1440, 1000), ("focus-warning", 390, 844),
        ("landing", 1440, 1000), ("teacher", 1440, 1100), ("student", 1440, 1000),
        ("login", 1440, 1000), ("builder", 1440, 1100), ("results", 1440, 1100),
        ("admin", 1440, 1100), ("staff-login", 1440, 1000), ("staff-signup", 1440, 1100),
        ("review", 1440, 1100), ("receipt", 1440, 1000),
        ("landing", 390, 1000), ("student", 390, 1100), ("teacher", 390, 1100),
        ("builder", 390, 1100), ("signup", 390, 1100), ("assessment", 390, 1100),
        ("login", 390, 1000), ("staff-login", 390, 1000), ("staff-signup", 390, 1100),
        ("results", 390, 1100), ("admin", 390, 1100), ("review", 390, 1100), ("receipt", 390, 1000),
        ("teacher", 768, 1100), ("builder", 1024, 1100), ("student", 320, 1100), ("landing", 320, 1100),
    ]
    if args.screens:
        cases = [case for case in cases if case[0] in args.screens]
    reports = []
    with tempfile.TemporaryDirectory(prefix="aralhub-preview-") as profile:
        process = subprocess.Popen(
            [str(edge), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--disable-background-networking", "--hide-scrollbars", f"--user-data-dir={profile}",
             "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1", "--remote-allow-origins=*", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        connection = None
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not active_port.exists():
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError("Preview browser did not start")
                time.sleep(.1)
            port = int(active_port.read_text().splitlines()[0])
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                targets = json.load(response)
            target = next(target for target in targets if target["type"] == "page")
            connection = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=10)
            message_id = 0

            def command(method, params=None):
                nonlocal message_id
                message_id += 1
                connection.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
                while True:
                    response = json.loads(connection.recv())
                    if response.get("id") == message_id:
                        if "error" in response:
                            raise RuntimeError(response["error"])
                        return response.get("result", {})

            command("Page.enable")
            for screen, width, height in cases:
                page = output / f"{screen}-{width}.html"
                page.write_text(preview_source(screen), encoding="utf-8")
                command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                command("Page.navigate", {"url": page.as_uri()})
                deadline = time.monotonic() + 10
                while True:
                    state = command("Runtime.evaluate", {"expression": "document.getElementById('uiLayoutCheck')?.content || ''", "returnByValue": True})
                    content = state.get("result", {}).get("value")
                    if content:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"Preview {screen} failed to render")
                    time.sleep(.1)
                screenshot = command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                page.with_suffix(".png").write_bytes(base64.b64decode(screenshot["data"]))
                report = {"screen": screen, "requested_width": width, **json.loads(content)}
                reports.append(report)
                print(json.dumps(report), flush=True)
        finally:
            if connection:
                connection.close()
            process.terminate()
            process.wait(timeout=10)
    report_name = "purple-notifications-layout-checks.json" if args.screens and "notifications" in args.screens else "shared-login-layout-checks.json" if args.screens and all(screen in ("login", "staff-login") for screen in args.screens) else "learning-materials-layout-checks.json" if args.screens and all(screen.endswith("-materials") for screen in args.screens) else "live-workflows-layout-checks.json" if args.screens else "layout-checks.json"
    (output / report_name).write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    if any(report["overflow"] or report.get("headerOverflow") for report in reports):
        raise SystemExit("Some views have horizontal overflow")


if __name__ == "__main__":
    main()
