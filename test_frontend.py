"""Run submission retry checks in a headless Edge browser, when installed."""

import os
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class SubmissionRetryTests(unittest.TestCase):
    def test_shared_login_routes_by_server_role_and_preserves_failed_credentials(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        login = re.findall(r"<script>(.*?)</script>", (root / "files/login.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  check(document.querySelector('label[for="li_username"]').textContent==='Username or student ID','Shared identifier label missing');
  check(!document.querySelector('select') && !document.querySelector('[name="role"]'),'Sign-in permits choosing a role');
  let paths=[], calls=[];navigateToPortal=path=>paths.push(path);
  apiRequest=async(method,path,body)=>{calls.push({method,path,body});return {role:'teacher',redirect:'https://untrusted.invalid'};};
  document.getElementById('li_username').value='teacher1';document.getElementById('li_password').value='teacher-pass';
  await doPortalLogin();
  check(paths[0]==='/teacher' && calls[0].path==='/api/auth/login' && !('role' in calls[0].body),'Teacher routing or trusted role boundary failed');
  for(const [role,destination] of [['student','/student'],['admin','/admin/']]) {
    apiRequest=async()=>({role});await doPortalLogin();check(paths.at(-1)===destination,'Wrong '+role+' destination');
  }
  apiRequest=async()=>{throw new Error('Incorrect username, student ID, or password.');};
  await doPortalLogin();
  check(document.querySelector('[role="alert"]').textContent.includes('Incorrect'),'Login error missing');
  check(document.getElementById('li_username').value==='teacher1' && document.getElementById('li_password').value==='teacher-pass','Login failure erased credentials');
  check(document.querySelector('.password-toggle') && document.querySelector('a[href="/?signup=1"]'),'Accessible login or signup entry missing');
  document.body.textContent='PASS: shared login routes by authenticated role';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + login + "\n" + checks, "PASS: shared login routes by authenticated role")

    def test_role_dashboards_restore_server_verified_identity_after_navigation(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        for role, filename, expected_view in (("student", "index.html", "studentHome"), ("teacher", "administrator.html", "adminHome")):
            with self.subTest(role=role):
                page = re.findall(r"<script>(.*?)</script>", (root / "files" / filename).read_text(encoding="utf-8"), re.S)[-1]
                setup = "window.ARALHUB_CURRENT_USER=" + json.dumps({"role": role, "name": "Example User", "username": "teacher1", "rollNo": "ID-001", "department": "BSIT", "departments": ["BSIT"], "yearLevel": "1st Year", "section": "A"}) + ";apiRequest=async()=>[];\n"
                checks = "setTimeout(()=>{try {if(state.currentUser!==window.ARALHUB_CURRENT_USER || state.view!==" + json.dumps(expected_view) + ")throw new Error('Dashboard did not restore verified identity');if(document.querySelector('.login-card'))throw new Error('Dashboard rendered a second sign-in page');document.body.textContent='PASS: verified dashboard identity';}catch(error){document.body.textContent='FAIL: '+error.message;}},0);"
                self.run_browser_check(helpers + "\n" + setup + page + "\n" + checks, "PASS: verified dashboard identity")

    def test_document_upload_uses_multipart_and_refreshes_expired_csrf(self):
        helpers = (Path(__file__).parent / "files/js/common.js").read_text(encoding="utf-8")
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  window.ARALHUB_ROLE='teacher'; _csrfToken='stale';
  const body=new FormData(); body.set('file',new File(['%PDF-1.4'],'lecture.pdf'));
  let posts=0;
  fetch=async(path,options)=>{
    check(options.headers['X-Portal-Role']==='teacher','Wrong upload session');
    if(path==='/api/csrf')return {ok:true,status:200,json:async()=>({csrfToken:'fresh'})};
    check(options.body===body && !('Content-Type' in options.headers),'Multipart body or boundary was changed');
    posts++;
    if(posts===1)return {ok:false,status:403,json:async()=>({code:'csrf_failed',error:'Expired token'})};
    check(options.headers['X-CSRFToken']==='fresh','Upload lost fresh CSRF token');
    return {ok:true,status:201,json:async()=>({ok:true})};
  };
  await apiRequest('POST','/api/learning/materials',body);
  check(posts===2,'Upload CSRF retry did not complete');
  document.body.textContent='PASS: multipart upload preserves file and CSRF';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + checks, "PASS: multipart upload preserves file and CSRF")

    def test_teacher_shares_lecture_and_reviews_activity_files(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        helpers += "\n" + (root / "files/js/learning.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  state.currentUser={role:'teacher',name:'Teacher'};state.view='learningHome';state.workspaceSection='materials';render();
  check(document.querySelector('.nav-item.active').textContent.includes('Lecture materials'),'Materials navigation not active');
  const form=document.querySelector('.learning-upload form');
  form.elements.title.value='Lecture <one>';form.elements.subject.value='Programming';form.elements.instructions.value='Complete <activity>';
  form.elements.requiresSubmission.checked=true;
  const choose=(department,year,section)=>{
    const di=DEPARTMENTS.indexOf(department), yi=YEAR_LEVELS.indexOf(year);
    const departmentInput=form.querySelector(`[name="lectureDepartment"][value="${department}"]`);departmentInput.checked=true;departmentInput.dispatchEvent(new Event('change'));
    const yearInput=document.getElementById(`lecture-department-${di}`).querySelector(`[name="lectureYear"][value="${year}"]`);yearInput.checked=true;yearInput.dispatchEvent(new Event('change'));
    const input=document.getElementById(`lecture-year-${di}-${yi}`).querySelector(`[name="lectureClass"][value="${section}"]`);input.checked=true;input.dispatchEvent(new Event('change'));
  };
  choose('BSIT','2nd Year','B');choose('BSCRIM','1st Year','C');choose('BSIT','3rd Year','A');
  const transfer=new DataTransfer();transfer.items.add(new File(['%PDF-1.4'],'lecture.pdf',{type:'application/pdf'}));form.elements.file.files=transfer.files;
  const crimIndex=DEPARTMENTS.indexOf('BSCRIM');
  toggleLearningDepartment(crimIndex,false);
  check(learningTargetClasses(form).length===2 && !learningTargetClasses(form).some(item=>item.department==='BSCRIM'),'Unchecked department still receives materials');
  toggleLearningDepartment(crimIndex,true);
  toggleLearningYear(DEPARTMENTS.indexOf('BSIT'),2,false);
  check(learningTargetClasses(form).length===2,'Unchecked year still receives materials');
  toggleLearningYear(DEPARTMENTS.indexOf('BSIT'),2,true);
  check(learningTargetClasses(form).length===3 && form.elements.file.files[0].name==='lecture.pdf' && form.elements.title.value==='Lecture <one>','Changing course selections lost chosen classes, file, or title');
  let fail=true,posts=0;
  const material={id:'lecture1',title:'Lecture <one>',subject:'Programming',instructions:'Complete <activity>',teacherName:'Teacher',createdAt:'2026-11-11T08:00:00+08:00',filename:'lecture.pdf',size:8,openUrl:'/api/learning/files/material/lecture1?portalRole=teacher',downloadUrl:'/api/learning/files/material/lecture1?portalRole=teacher&download=1',requiresSubmission:true,submissionCount:1,targetClasses:[{department:'BSIT',yearLevel:'2nd Year',section:'B'}]};
  apiRequest=async(method,path,data)=>{
    if(method==='POST'){
      posts++;check(data instanceof FormData && data.get('file').name==='lecture.pdf','Lecture file missing');
      const targets=JSON.parse(data.get('targetClasses'));
      check(data.get('requiresSubmission')==='true' && targets.length===3 && targets.some(item=>item.department==='BSIT' && item.yearLevel==='2nd Year' && item.section==='B') && targets.some(item=>item.department==='BSCRIM' && item.yearLevel==='1st Year' && item.section==='C'),'Recipients from different courses or years missing');
      if(fail)throw new Error('Connection interrupted');return {ok:true};
    }
    if(path.endsWith('/submissions'))return [{id:'submission1',name:'Student <One>',rollNo:'ID-001',department:'BSIT',yearLevel:'2nd Year',section:'B',filename:'activity.xlsx',size:200,submittedAt:material.createdAt,openUrl:'/submission',downloadUrl:'/submission?download=1'}];
    return [material];
  };
  await publishLectureMaterial(form);
  check(form.elements.file.files[0].name==='lecture.pdf' && form.elements.title.value==='Lecture <one>' && !form.querySelector('fieldset').disabled,'Upload error lost selected file or fields');
  check(learningTargetClasses(form).length===3 && form.querySelector('.learning-class-count').textContent==='3 classes selected','Upload error lost multi-department class selections');
  check(form.querySelector('[role="alert"]').textContent.includes('interrupted'),'Upload error not shown');
  fail=false;await publishLectureMaterial(form);
  check(posts===2 && document.querySelector('.learning-card h2').textContent==='Lecture <one>','Lecture was not shared');
  check(!document.querySelector('.learning-card one'),'Lecture title was not escaped');
  await openLearningSubmissions('lecture1');
  check(document.querySelector('.learning-received-row').textContent.includes('Student <One>') && document.querySelector('.learning-received-row').textContent.includes('activity.xlsx'),'Teacher cannot review student file');
  deleteLectureMaterial('lecture1');
  check(document.querySelector('.modal-box').textContent.includes('all activity submissions') && document.querySelectorAll('.modal-actions button').length===2,'Delete does not explain removal or offer cancel');
  document.body.textContent='PASS: teacher shares lectures and reviews files';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: teacher shares lectures and reviews files")

    def test_student_opens_material_and_submits_then_replaces_activity_file(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        helpers += "\n" + (root / "files/js/learning.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const material={id:'lecture1',title:'Activity',subject:'Programming',instructions:'Read and submit',teacherName:'Teacher',createdAt:'2026-11-11T08:00:00+08:00',filename:'lecture.pdf',size:100,openUrl:'/material?portalRole=student',downloadUrl:'/material?portalRole=student&download=1',requiresSubmission:true,mySubmission:null};
  state.currentUser={name:'Student',rollNo:'ID-001'};let posts=0;
  apiRequest=async(method,path,data)=>{
    if(method==='GET')return [material];
    check(path.endsWith('/lecture1/submissions') && data instanceof FormData,'Wrong submission destination');
    posts++;material.mySubmission={id:'submission1',filename:data.get('file').name,size:8,submittedAt:material.createdAt,openUrl:'/submission?portalRole=student',downloadUrl:'/submission?portalRole=student&download=1'};
    return {ok:true,submission:material.mySubmission};
  };
  await openLearningWorkspace();
  check(!document.querySelector('.learning-upload') && document.querySelector('.learning-file-actions a').getAttribute('href')===material.openUrl,'Student material access broken');
  const upload=async name=>{const form=document.querySelector('.learning-submission form');const transfer=new DataTransfer();transfer.items.add(new File(['%PDF-1.4'],name));form.elements.file.files=transfer.files;await submitLearningFile(form,'lecture1');};
  await upload('completed.pdf');
  check(document.querySelector('.learning-submission').textContent.includes('completed.pdf') && document.querySelector('.learning-card .badge').textContent==='Submitted','Submission confirmation missing');
  check(document.querySelector('.learning-submission button').textContent==='Replace submission','Replacement action missing');
  await upload('revised.pdf');
  check(posts===2 && document.querySelector('.learning-submission').textContent.includes('revised.pdf') && !document.querySelector('.learning-submission').textContent.includes('completed.pdf'),'Replacement did not update student file');
  document.body.textContent='PASS: student opens materials and submits activity files';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: student opens materials and submits activity files")

    def test_account_delete_requires_delete_word_for_students_and_teachers(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  state.currentUser={role:'admin',name:'Admin'};
  state.students=[{id:'s',name:'Duplicate Student',roll_no:'S1',department:'BSIT'}];
  render=()=>{document.getElementById('app').innerHTML=renderModalHtml();};
  let calls=[], refreshes=0;
  apiRequest=async(method,path,body)=>{check(method==='DELETE' && body.confirmation==='DELETE','Delete word was not sent');calls.push(path);return {ok:true};};
  goAdminHome=async()=>{refreshes++;render();};
  const type=value=>{const input=document.getElementById('dialogInput');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));};
  for(const [open,path] of [[()=>archiveStudent('s'),'/api/students/s'],[()=>removeTeacher('t','Teacher'),'/api/teachers/t']]) {
    const before=calls.length;
    open(); check(document.getElementById('dialogInput').value==='','Delete confirmation was pre-filled');
    check(document.querySelector('.modal-box').textContent.includes('cannot be retrieved'),'Super admin deletion must warn that it is permanent');
    if(path==='/api/students/s') check(document.querySelector('.modal-box').textContent.includes('exam results and returned submissions will also be permanently deleted'),'Permanent student deletion must warn that exam records are deleted');
    _modalConfirm(); check(calls.length===before,'Empty confirmation deleted account');
    type('delete'); _modalConfirm(); check(calls.length===before && document.querySelector('[role="alert"]'),'Lowercase confirmation deleted account');
    closeModal(); check(calls.length===before,'Cancel deleted account');
    open(); type('DELETE'); _modalConfirm(); await new Promise(resolve=>setTimeout(resolve,0));
    check(calls.length===before+1 && calls.at(-1)===path,'Confirmed deletion did not target selected account');
  }
  check(refreshes===2,'Account lists did not refresh after deleting');
  state.currentUser={role:'teacher',name:'Teacher'}; archiveStudent('s');
  check(document.querySelector('.modal-box').textContent.includes('Only the super admin can retrieve') && !document.querySelector('.modal-box').textContent.includes('cannot be retrieved'),'Teacher deletion must remain recoverable by super admin');
  closeModal();
  document.body.textContent='PASS: account deletion requires DELETE confirmation';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks,
                               "PASS: account deletion requires DELETE confirmation")

    def test_teacher_return_requires_typed_student_id_and_handles_mismatch(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  state.currentUser={role:'teacher',name:'Teacher',departments:['BSIT']};
  state.view='adminResults'; state.currentExamResults=[{id:'r',rollNo:'ID-001',activityType:'exam'}];
  render=()=>{document.getElementById('app').innerHTML=renderModalHtml();};
  let calls=0;
  apiRequest=async(method,path,body)=>{
    calls++; check(method==='DELETE' && path==='/api/results/r','Wrong return endpoint');
    check(body.studentId=== (calls===1?'WRONG':'ID-001'),'Entered ID was not sent for verification');
    if(calls===1){const error=new Error('Student ID does not match this submission.');error.code='student_id_verification_failed';throw error;}
    return {ok:true};
  };
  reopenAdminResult('r');
  check(document.getElementById('dialogInput').value==='','Student ID must be entered manually');
  _modalConfirm();
  check(calls===0 && document.querySelector('[role="alert"]'),'Blank ID did not block confirmation');
  const enter=value=>{const input=document.getElementById('dialogInput');input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));};
  enter('WRONG'); _modalConfirm(); await new Promise(resolve=>setTimeout(resolve,0));
  check(calls===1 && state.currentExamResults.length===1 && document.querySelector('.modal-box').textContent.includes('does not match'),'Mismatch did not preserve the submission and allow retry');
  enter(' ID-001 '); _modalConfirm(); await new Promise(resolve=>setTimeout(resolve,0));
  check(calls===2 && state.currentExamResults.length===0 && !_modal,'Verified return did not complete');
  document.body.textContent='PASS: teacher return verifies manually entered student ID';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks,
                               "PASS: teacher return verifies manually entered student ID")

    def test_student_review_displays_correct_answers_for_every_question_type(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(() => {try {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  state.lastResult={id:'submitted',score:1,total:6,percent:100/6};
  state.studentReview=[
    {type:'multiple_choice',text:'Sum',options:['3','4'],chosen:0,correct:1,isCorrect:false,pointsAwarded:0,pointsPossible:2},
    {type:'identification',text:'City',chosen:'Other',answer:'<Manila & city>',isCorrect:false,pointsAwarded:0,pointsPossible:2},
    {type:'true_false',text:'Statement',options:['True','False'],chosen:1,correct:0,isCorrect:false,pointsAwarded:0,pointsPossible:1},
    {type:'matching',text:'Device',options:['Monitor','Printer'],chosen:1,correct:1,isCorrect:true,pointsAwarded:1,pointsPossible:1},
    {type:'matching',text:'Unanswered',options:['Keyboard','Mouse'],chosen:null,correct:0,isCorrect:false,pointsAwarded:0,pointsPossible:1}
  ];
  document.getElementById('app').innerHTML=renderStudentResult();
  const rows=[...document.querySelectorAll('.review-item')];
  ['4','<Manila & city>','True','Printer','Keyboard'].forEach((answer,i)=>{
    check(rows[i].textContent.includes('Correct answer: '+answer),'Missing correct answer for '+state.studentReview[i].type);
  });
  check(rows[0].textContent.includes('Your answer: 3'),'Student answer was replaced');
  check(rows[4].textContent.includes('Your answer: Not answered'),'Unanswered item was lost');
  check(!rows[1].querySelector('manila'),'Answer text was interpreted as HTML');
  document.body.textContent='PASS: student review shows correct answers for every question type';
}catch(error){document.body.textContent='FAIL: '+error.message;}})();
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks,
                               "PASS: student review shows correct answers for every question type")

    def run_browser_check(self, script, expected):
        edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
        if not edge.is_file():
            self.skipTest("Microsoft Edge is not installed")
        with tempfile.TemporaryDirectory(prefix="aralhub-browser-") as directory:
            root = Path(directory)
            page = root / "exam-test.html"
            page.write_text('<!doctype html><body><div id="app"></div><script>' + script + "</script>", encoding="utf-8")
            result = subprocess.run(
                [str(edge), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                 "--disable-background-networking", f"--user-data-dir={root / 'profile'}",
                 "--virtual-time-budget=5000", "--dump-dom", page.as_uri()],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-1500:])
            self.assertRegex(result.stdout, r"<body[^>]*>" + re.escape(expected), result.stdout[-3000:] + result.stderr[-1000:])

    def test_teacher_return_refreshes_only_rejected_csrf_without_signing_in(self):
        helper = (Path(__file__).parent / "files/js/common.js").read_text(encoding="utf-8")
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  window.ARALHUB_ROLE='teacher'; _csrfToken='stale'; let writes=0,tokens=0,logins=0;
  window.fetch=async(path,options)=>{
    check(options.headers['X-Portal-Role']==='teacher','Teacher request used the wrong session');
    if(path==='/api/csrf'){tokens++;return {ok:true,status:200,json:async()=>({csrfToken:'fresh'})};}
    if(path.includes('/login'))logins++;
    writes++;
    if(writes===1)return {ok:false,status:403,json:async()=>({error:'Expired token',code:'csrf_failed'})};
    check(options.headers['X-CSRFToken']==='fresh','Return did not use the refreshed token');
    return {ok:true,status:200,json:async()=>({ok:true})};
  };
  const returned=await apiRequest('DELETE','/api/results/submitted');
  check(returned.ok && writes===2 && tokens===1 && logins===0,'Returning a result required another login or duplicated the action');
  writes=0;
  window.fetch=async()=>{writes++;return {ok:false,status:403,json:async()=>({error:'Not your result',code:'not_owner'})};};
  await apiRequest('DELETE','/api/results/other').catch(()=>{});
  check(writes===1,'A permission failure was automatically retried');
  window.ARALHUB_ROLE='student';
  window.fetch=async(path,options)=>{check(options.headers['X-Portal-Role']==='student','Student request used the teacher session');return {ok:true,status:200,json:async()=>[]};};
  await apiRequest('GET','/api/exams?studentView=1');
  document.body.textContent='PASS: teacher return refreshes security token without login';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helper + "\n" + checks, "PASS: teacher return refreshes security token without login")

    def test_student_workspace_handles_expired_sessions_and_reconnects_only_transient_errors(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  let loginDestination='';navigateToPortal=path=>{loginDestination=path;};
  const user={name:'Student',rollNo:'S1',department:'BSIT'};
  state.currentUser=user;setView('studentHome');let calls=0;
  apiRequest=async()=>{calls++;const error=new Error('Student sign in required');error.status=401;throw error;};
  await refreshStudentWorkspace();
  check(state.view==='studentLogin' && !state.currentUser && state.errorMsg.includes('session has expired'),'Expired login was described as a connection failure');
  check(loginDestination==='/login?expired=1','Expired session did not return to the shared login page');
  const after=calls;await refreshStudentWorkspace();check(calls===after,'Expired student session kept polling');
  state.currentUser=user;
  apiRequest=async()=>{const error=new Error('Server busy; try again shortly');error.status=503;throw error;};
  await goStudentHome();
  check(state.view==='studentHome' && state.connError==='Server busy; try again shortly','Initial server error was hidden by a generic connection warning');
  apiRequest=async()=>[];await refreshStudentWorkspace();
  check(!state.connError && state.currentUser===user,'Student workspace did not recover after reconnection');
  apiRequest=async()=>{const error=new Error('This request is not permitted');error.status=403;throw error;};
  await refreshStudentWorkspace();
  check(state.studentLiveBlocked && state.connError==='This request is not permitted','Permanent permission failure was described as offline');
  apiRequest=async()=>[];await goStudentHome();
  check(!state.studentLiveBlocked && !state.connError,'Try again did not clear a blocked refresh');
  document.body.textContent='PASS: student session and connection recovery';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: student session and connection recovery")

    def test_teacher_publish_sign_in_recovery_keeps_fifty_imported_questions(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  const account={role:'teacher',username:'teacher1',name:'Teacher',department:'BSIT',departments:['BSIT']};
  const text='Part 1\n'+Array.from({length:50},(_,i)=>`Question: Item ${i+1}\nA. Yes\nB. No\nC. Maybe\nD. Unsure\nAnswer: A`).join('\n\n');
  for(const [status,code] of [[401,'staff_session_expired'],[403,'teacher_required'],[403,'teacher_account_changed']]) {
    state.currentUser={...account}; startCreateExam();
    await importQuestions(new File([text],'MIDTERM_EXAM_50_ITEMS.txt'));
    Object.assign(state.draft,{title:'Midterm',subject:'Computing',targetGroups:[{department:'BSIT',yearLevels:['1st Year'],sections:['A']}]});
    const draft=state.draft, original=JSON.stringify(draft.questions);
    let posts=0,published,loginRole='admin';
    apiRequest=async(method,path,payload)=>{
      if(path==='/api/admin/login')return loginRole==='teacher'?account:{role:'admin',redirect:'/admin/'};
      if(method==='POST' && path==='/api/exams') {
        posts++; if(posts===1){const error=new Error('Teacher session expired or changed');error.status=status;error.code=code;throw error;}
        published=payload;return {id:'published'};
      }
      return [];
    };
    await saveExam();
    check(state.view==='createExam' && state.draft===draft && draft.questions.length===50,'Failed publish lost imported questions');
    check(document.querySelector('#publishTeacherUsername')?.value==='teacher1' && !document.querySelector('[data-publish-activity]').disabled,'Recovery form or retry button is missing');
    document.querySelector('#publishTeacherPassword').value='sample-password';
    await signInForPublishing();
    check(state.publishAuthRequired && state.view==='createExam','Super admin sign-in bypassed teacher publishing');
    check(JSON.stringify(draft.questions)===original,'Wrong-account sign-in changed imported answers');
    loginRole='teacher';document.querySelector('#publishTeacherPassword').value='sample-password';
    await signInForPublishing();
    check(!state.publishAuthRequired && state.view==='createExam' && state.draft===draft,'Teacher sign-in lost the editor');
    check(JSON.stringify(draft.questions)===original && state.successMsg.includes('50'),'Teacher sign-in changed the imported assessment');
    await saveExam();
    check(published?.questions.length===50 && published.expectedTeacherUsername==='teacher1','Retry did not publish the complete imported assessment');
    check(state.view==='adminHome' && posts===2,'Publishing did not finish after teacher recovery');
  }
  document.body.textContent='PASS: teacher publishing recovery preserves fifty questions';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: teacher publishing recovery preserves fifty questions")

    def test_exam_and_quiz_point_labels_and_exports_follow_activity_type(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(() => {try {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  for (const kind of ['exam','quiz']) for (const type of ['true_false','matching']) check(assessmentPoints({activityType:kind},{type})===1, 'True/False and Matching must each be one point');
  state.currentUser={role:'teacher',name:'Teacher',departments:['BSIT']};
  startCreateExam(); state.draft.title='Keep my title'; state.draft.questions[0].text='Keep my question'; render();
  for(const [kind,points] of [['quiz',1],['exam',2]]) {
    const picker=document.querySelector(`[name="builderActivityType"][value="${kind}"]`);
    picker.checked=true; picker.dispatchEvent(new Event('change',{bubbles:true}));
    check(document.querySelector('.qnum').textContent.includes(`${points} POINT`),'Question point label did not update');
    check(document.querySelector('.builder-header p').textContent.includes(`${points} point`),'Builder point explanation did not update');
    check(state.draft.title==='Keep my title' && state.draft.questions[0].text==='Keep my question','Switching type lost draft work');
    const result={id:'r',examId:'a',examTitle:'Assessment',activityType:kind,name:'Student',rollNo:'S1',department:'BSIT',yearLevel:'1st Year',section:'A',score:points,total:points*2,percent:50,submittedAt:'2026-10-21T09:00:00',review:[{text:'Question',chosen:0,correct:0,isCorrect:true,options:['A','B']}]};
    state.adminReviewResult=result;
    check(renderAdminResultReview().includes(`${points} point`) && renderAdminResultReview().includes(`${points} / ${points} points`),'Review has the wrong point value');
    state.currentExamResults=[result]; state.adminResultsExamId='a'; state.exams=[{id:'a',activityType:kind,questionCount:2}];
    let exported;
    window.XLSX={utils:{book_new:()=>({}),json_to_sheet:rows=>{exported=rows;return {};},encode_cell:()=> 'A1',encode_range:()=> 'A1:N2',book_append_sheet:()=>{}},writeFile:()=>{}};
    check(downloadResultsExcel(true) && exported[0]['Scoring']===assessmentScoringLabel(result),'Excel exported the wrong point value');
    let table;
    window.jspdf={jsPDF:function(){return new Proxy({internal:{pageSize:{getWidth:()=>297,getHeight:()=>210}},lastAutoTable:{finalY:80}}, {get:(target,key)=>key==='autoTable'?(options)=>{table=options;}:key in target?target[key]:()=>{}});}};
    check(downloadResultsPdf(true) && table.head[0][5]==='Score (points)','PDF exported the wrong point value');
  }
  document.body.textContent='PASS: activity points in builder, reviews and exports';
}catch(error){document.body.textContent='FAIL: '+error.message;}})();
"""
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: activity points in builder, reviews and exports")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(() => {try {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  state.currentUser={role:'student',name:'Student',rollNo:'S1'};
  for(const [kind,points] of [['exam',2],['quiz',1]]) {
    state.runtime={exam:{title:'Assessment',activityType:kind,duration:10,questions:[{id:'q',type:'multiple_choice',text:'Question',options:['A','B']}]},answers:{},currentIdx:0,secondsLeft:600};
    setView('takeExam');
    check(document.querySelector('.question-count').textContent.includes(`${points} point`),'Student question value is incorrect');
    check(document.querySelector('.exam-context').textContent.includes(`${points} point`),'Student instructions have the wrong value');
    state.lastResult={examTitle:'Assessment',activityType:kind,score:points,total:points*2,percent:50};
    check(renderStudentResult().includes(assessmentScoringLabel(state.lastResult)),'Receipt has the wrong point value');
  }
  state.runtime=null; document.body.textContent='PASS: exam and quiz student point labels';
}catch(error){document.body.textContent='FAIL: '+error.message;}})();
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: exam and quiz student point labels")

    def test_student_forms_keep_entries_and_use_accessible_controls(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  setView('studentLogin');
  document.querySelector('#li_username').value = 'TEST-ID';
  document.querySelector('#li_password').value = 'sample-password';
  check(document.querySelector('label[for="li_password"]').control.id === 'li_password', 'Password label is not connected');
  const toggle = document.querySelector('.password-toggle');
  toggle.click();
  check(document.querySelector('#li_password').type === 'text' && toggle.getAttribute('aria-pressed') === 'true', 'Show password failed');
  toggle.click();
  check(document.querySelector('#li_password').type === 'password', 'Hide password failed');
  let calls = 0, complete;
  doStudentLogin = () => { calls++; return new Promise(resolve => { complete = resolve; }); };
  const form = document.querySelector('form');
  form.requestSubmit(); form.requestSubmit();
  check(calls === 1 && form.querySelector('[type="submit"]').disabled, 'Duplicate form submission was allowed');
  complete(); await new Promise(resolve => setTimeout(resolve, 0));
  check(!form.querySelector('[type="submit"]').disabled, 'Sign-in button was not restored');
  state.errorMsg = 'Please check your details.'; render();
  check(document.querySelector('#li_username').value === 'TEST-ID' && document.querySelector('#li_password').value === 'sample-password', 'Validation erased login entries');
  check(document.activeElement.getAttribute('role') === 'alert', 'Validation message was not announced');
  setView('studentSignup');
  document.querySelector('#up_first_name').value = 'Example';
  document.querySelector('#up_last_name').value = 'Student';
  document.querySelector('#up_middle_initial').value = 'A.';
  document.querySelector('#up_roll').value = 'TEST-ID';
  document.querySelector('#up_dept').value = 'BSIT';
  document.querySelector('#up_dept').dispatchEvent(new Event('change'));
  check(document.querySelector('#up_section').disabled, 'Sections appeared before selecting a year');
  document.querySelector('#up_year').value = '1st Year';
  document.querySelector('#up_year').dispatchEvent(new Event('change'));
  check([...document.querySelector('#up_section').options].map(option => option.value).join(',') === ',A', 'Signup did not filter sections by department');
  document.querySelector('#up_year').value = '2nd Year';
  document.querySelector('#up_year').dispatchEvent(new Event('change'));
  check([...document.querySelector('#up_section').options].map(option => option.value).join(',') === ',A,B,C', 'Signup did not filter sections by year');
  document.querySelector('#up_section').value = 'C';
  document.querySelector('#up_year').value = '1st Year';
  document.querySelector('#up_year').dispatchEvent(new Event('change'));
  check(document.querySelector('#up_section').value === '' && document.querySelector('#signupSectionLabel').textContent.includes('1st Year'), 'Changing year retained an invalid section or stale label');
  check(!document.querySelector('#up_teacher'), 'Students can still select teachers');
  state.errorMsg = 'Please complete your year level.'; render();
  check(document.querySelector('#up_first_name').value === 'Example' && document.querySelector('#up_last_name').value === 'Student' && document.querySelector('#up_middle_initial').value === 'A.', 'Validation erased name fields');
  check(document.querySelector('#up_dept').value === 'BSIT', 'Validation erased program');
  document.querySelector('#up_dept').dispatchEvent(new Event('change'));
  document.querySelector('#up_year').value = '1st Year';
  document.querySelector('#up_year').dispatchEvent(new Event('change'));
  document.querySelector('#up_section').value = 'A';
  document.querySelector('#up_password').value = 'sample-password';
  document.querySelector('#up_password2').value = 'sample-password';
  let payload;
  apiRequest = async (method, path, body) => { check(method === 'POST' && path === '/api/students/signup', 'Signup loaded teachers'); payload = body; return {}; };
  let signupDestination='';navigateToPortal=path=>{signupDestination=path;};
  await doStudentSignup();
  check(payload.firstName === 'Example' && payload.lastName === 'Student' && payload.middleInitial === 'A.', 'Separate names were not submitted');
  check(!('teacherUsernames' in payload) && !('teacherUsername' in payload), 'Signup submitted teacher choices');
  check(signupDestination === '/login?registered=1', 'Signup did not return to the shared login');
  document.body.textContent = 'PASS: accessible student forms';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        school_options = """window.ARALHUB_SCHOOL_OPTIONS = {
          departments:['BSIT','BSHM'], year_level:['1st Year','2nd Year','3rd Year','4th Year'],
          section:['A','B','C'], sections_by_department:{BSIT:['A'],BSHM:['A','B','C']},
          sections_by_department_and_year:{BSIT:{'1st Year':['A'],'2nd Year':['A','B','C']}}
        };"""
        self.run_browser_check(school_options + "\n" + helpers + "\n" + student + "\n" + checks, "PASS: accessible student forms")

    def test_focus_warning_precedes_submission_for_exams_and_quizzes(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(() => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  const originalNow=Date.now; let now=originalNow(); Date.now=()=>now;
  Object.defineProperty(document,'hidden',{configurable:true,value:false});
  document.hasFocus=()=>true;
  let submissions=[];
  submitExam=(automatic,reason)=>{ if(state.submitting)return; state.submitting=true; submissions.push({automatic,reason}); };
  state.currentUser={name:'Student',rollNo:'FOCUS-TEST'};
  for(const activityType of ['exam','quiz']) {
    state.submitting=false;
    state.runtime={exam:{id:'focus-'+activityType,title:'Focus test',activityType,duration:30,questions:[{id:'q1',type:'multiple_choice',text:'Question',options:['A','B']}]},answers:{q1:1},currentIdx:0,secondsLeft:1800,deadlineAt:now+1800000,submissionId:'attempt-'+activityType};
    setView('takeExam');
    window.dispatchEvent(new Event('blur'));
    check(document.querySelector('[role="alertdialog"]') && submissions.length===(activityType==='exam'?0:1),'Leaving did not display a warning before submission');
    const deadline=state.runtime.focusDeadlineAt;
    check(deadline===now+10000,'Warning is not ten seconds');
    Object.defineProperty(document,'hidden',{configurable:true,value:true});
    document.dispatchEvent(new Event('visibilitychange'));
    check(state.runtime.focusDeadlineAt===deadline,'Duplicate focus events reset the countdown');
    check(readSavedAttempt().focusDeadlineAt===deadline,'Warning deadline was not saved for reload recovery');
    selectAnswer('q1',0); check(state.runtime.answers.q1===1,'Answers changed behind the warning');
    Object.defineProperty(document,'hidden',{configurable:true,value:false});
    now+=2000; acknowledgeAssessmentFocus();
    check(!state.runtime.focusDeadlineAt && !document.querySelector('[role="alertdialog"]'),'Returning could not dismiss the warning');
    warnAssessmentFocus(); now+=10001; tickTimer(); tickTimer();
    check(submissions.length===(activityType==='exam'?1:2),'Expired warning did not produce exactly one submission');
    check(submissions.at(-1).automatic && submissions.at(-1).reason==='tab_switch','Focus reason was lost');
  }
  state.runtime=null; state.submitting=false; Date.now=originalNow; clearSavedAttempt();
  document.body.textContent='PASS: assessment focus warning and countdown';
})()
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: assessment focus warning and countdown")

    def test_assessment_activity_counts_transitions_and_survives_resume_and_retry(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  let now=1794441600000, hidden=false, focused=true;
  Date.now=()=>now;
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>hidden});
  document.hasFocus=()=>focused;
  render=()=>{};
  const exam={id:'activity-test',title:'Activity test',activityType:'exam',duration:30,questions:[{id:'q1',text:'Question',type:'multiple_choice',options:['A','B']}]};
  let posts=[],monitorUpdates=[],fail=true;
  apiRequest=async(method,path,payload)=>{
    if(path.endsWith('/take'))return exam;
    if(path.endsWith('/activity')){monitorUpdates.push(JSON.parse(JSON.stringify(payload)));return {ok:true};}
    if(method==='POST'){
      posts.push(JSON.parse(JSON.stringify(payload)));
      if(fail)throw new Error('Offline');
      return {id:'activity-result',examId:exam.id,score:0,total:2};
    }
    return [];
  };
  state.currentUser={name:'Student',rollNo:'ACTIVITY-001'};
  window.dispatchEvent(new Event('blur'));
  check(!readSavedAttempt(),'Activity recorded outside an assessment');
  await beginExam(exam.id);clearInterval(state.runtime.timerId);
  focused=false;
  window.dispatchEvent(new Event('blur'));window.dispatchEvent(new Event('blur'));
  const count=type=>state.runtime.activityLog.events.filter(e=>e.type===type).length;
  check(count('focus_lost')===1 && count('page_hidden')===0,'Visible focus loss was mislabeled or duplicated');
  hidden=true;document.dispatchEvent(new Event('visibilitychange'));document.dispatchEvent(new Event('visibilitychange'));
  check(count('page_hidden')===1 && count('warning_started')===1,'One departure duplicated events or warning');
  now+=1000;hidden=false;document.dispatchEvent(new Event('visibilitychange'));
  focused=true;window.dispatchEvent(new Event('focus'));window.dispatchEvent(new Event('focus'));
  acknowledgeAssessmentFocus();
  check(count('page_visible')===1 && count('focus_returned')===1 && count('warning_acknowledged')===1,'Return observations missing or duplicated');
  focused=false;window.dispatchEvent(new Event('blur'));
  now+=1000;focused=true;window.dispatchEvent(new Event('focus'));acknowledgeAssessmentFocus();
  check(count('focus_lost')===2 && count('page_hidden')===1,'Distinct second focus loss was not counted');
  await syncAssessmentActivity();await syncAssessmentActivity();
  check(monitorUpdates.at(-1).activityLog.events.filter(e=>e.type==='focus_lost').length===2,'Activity was not sent before submission');
  const before=readSavedAttempt();
  check(before.activityLog.events.length===state.runtime.activityLog.events.length,'Activity was not saved locally');
  state.runtime=null;state.savedAttempt=before;
  await resumeSavedAttempt(exam.id);clearInterval(state.runtime.timerId);
  check(count('focus_lost')===2 && count('page_hidden')===1 && count('attempt_resumed')===1,'Resume lost activity history');
  warnAssessmentFocus();now+=10001;
  await submitExam(true,'tab_switch');clearInterval(state.runtime.timerId);
  const saved=readSavedAttempt();
  check(saved.pendingSubmission==='tab_switch' && saved.activityLog.events.at(-1).type==='submit_tab_switch','Offline automatic submission lost activity or trigger');
  fail=false;await submitExam(true,state.runtime.pendingSubmission);
  check(posts.length===2 && JSON.stringify(posts[0].activityLog)===JSON.stringify(posts[1].activityLog),'Retry changed the submitted evidence');
  check(!readSavedAttempt() && state.view==='studentResult','Receipt did not clear local attempt');
  document.body.textContent='PASS: assessment activity counts, resume and retry';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: assessment activity counts, resume and retry")

    def test_teacher_activity_review_distinguishes_observations_and_missing_logs(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(() => {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  let html=renderAssessmentActivity({});
  check(html.includes('not recorded') && !html.includes('class="value">0'),'Legacy attempt implied zero focus losses');
  const summary={focusLossCount:2,hiddenCount:1,warningCount:2,complete:true,truncated:false};
  const result={activitySummary:summary,activityLog:{events:[
    {type:'focus_lost',at:1794441600000,hidden:false,focused:false},
    {type:'page_hidden',at:1794441601000,hidden:true,focused:false},
    {type:'submit_tab_switch',at:1794441610000,hidden:false,focused:true},
  ]}};
  html=renderAssessmentActivity(result);
  const box=document.createElement('div');box.innerHTML=html;
  check(box.querySelectorAll('tbody tr').length===3,'Activity timeline is missing');
  check(html.includes('>2</div>') && html.includes('>1</div>'),'Separate event counts missing');
  check(html.includes('cannot identify which action') && html.includes('do not add these counts'),'Review claims an exact OS action');
  check(html.includes('focus warning expired') && html.includes('Student device time'),'Trigger or timestamp label missing');
  result.activitySummary={...summary,complete:false,truncated:true};
  html=renderAssessmentActivity(result);
  check(html.includes('Partial log') && html.includes('first 2,000'),'Incomplete evidence is not identified');
  document.body.textContent='PASS: teacher browser activity review';
})()
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: teacher browser activity review")

    def test_exam_answers_persist_and_resume_after_reload(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  const exam = {
    id:'persistent-exam', title:'Saved work', activityType:'exam', duration:30,
    questions:[{id:'q1',type:'multiple_choice',text:'First?',options:['A','B']},{id:'q2',type:'multiple_choice',text:'Second?',options:['C','D']}]
  };
  const assigned = {id:exam.id,title:exam.title,activityType:'exam',duration:30,questionCount:2};
  render = () => {};
  createSubmissionId = () => 'stable-attempt-id';
  state.currentUser = {name:'Student',rollNo:'PERSIST-001',department:'BSIT',section:'A',yearLevel:'1st Year'};
  state.exams = [assigned]; state.myResults = [];
  apiRequest = async (method, path) => {
    if (path === '/api/exams?studentView=1') return [assigned];
    if (path.startsWith('/api/results?rollNo=')) return [];
    if (path === `/api/exams/${exam.id}/take`) return exam;
    throw new Error('Unexpected API request: ' + path);
  };
  await beginExam(exam.id);
  selectAnswer('q1', 1);
  jumpTo(1);
  setIdentificationAnswer('q2', 'saved text');
  const key = savedAttemptStorageKey();
  const saved = JSON.parse(localStorage.getItem(key));
  check(saved.answers.q1 === 1 && saved.answers.q2 === 'SAVED TEXT', 'Answers were not persisted immediately');
  check(saved.currentQuestionId === 'q2' && saved.submissionId === 'stable-attempt-id', 'Attempt position or stable submission ID was not persisted');
  clearInterval(state.runtime.timerId);
  state.runtime = null;
  state.savedAttempt = null;
  await goStudentHome();
  check(state.savedAttempt?.examId === exam.id, 'Saved attempt was not recovered after re-opening the workspace');
  check(renderStudentHome().includes('Resume saved attempt'), 'Student workspace did not offer to resume');
  await resumeSavedAttempt(exam.id);
  check(state.runtime.answers.q1 === 1 && state.runtime.answers.q2 === 'SAVED TEXT', 'Answers were not restored');
  check(state.runtime.currentIdx === 1 && state.runtime.submissionId === 'stable-attempt-id', 'Question position or submission identity was not restored');
  clearInterval(state.runtime.timerId);
  clearSavedAttempt();
  document.body.textContent = 'PASS: saved exam answers resume';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: saved exam answers resume")

    def test_teacher_department_checkboxes_and_student_directory_search(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  setView('adminLogin');
  check(!document.querySelector('#tu_name') && !document.querySelector('[onclick*="teacherSignup"]'), 'Public teacher signup is still available');
  check(document.querySelector('.wrap-inner .help-text')?.textContent.includes('school administrator'), 'Teacher account instructions are missing');
  state.currentUser = {role:'teacher',name:'Teacher',departments:['BSIT']};
  state.students = [
    {id:'one',name:'Example, One A.',roll_no:'S-001',department:'BSIT',section:'A',year_level:'1st Year'},
    {id:'two',name:'Sample, Two B.',roll_no:'S-002',department:'BSIT',section:'B',year_level:'2nd Year'},
  ];
  setView('adminHome');
  await openWorkspaceSection('students');
  check(document.querySelector('.student-password-panel').open, 'Student navigation left directory closed');
  check(!document.querySelector('#student-directory'), 'Students displayed before department, year, and section selection');
  document.querySelector('[data-student-department="BSIT"]').click();
  check(!document.querySelector('#student-directory'), 'Department selection displayed students without a section');
  const year = document.querySelector('#studentYearFilter');
  year.value = '2nd Year'; year.dispatchEvent(new Event('change'));
  check(!document.querySelector('#student-directory'), 'Year selection displayed students without a section');
  const section = document.querySelector('#studentSectionFilter');
  section.value = 'B'; section.dispatchEvent(new Event('change'));
  const input = document.querySelector('.table-tools input');
  input.value = 's-002'; input.dispatchEvent(new Event('input'));
  check(document.querySelectorAll('#student-directory tbody tr:not([hidden])').length === 1, 'ID search failed');
  check(document.querySelector('#student-directory tbody tr:not([hidden])').textContent.includes('Sample'), 'Search showed the wrong student');
  input.value = 'missing'; input.dispatchEvent(new Event('input'));
  check(document.querySelector('#student-directory-status').textContent.includes('No matching records'), 'Missing search feedback');
  check(document.querySelector('#student-directory button[onclick^="archiveStudent("]')?.textContent.trim() === 'DELETE', 'Active student delete action is missing');
  state.archivedStudents = [{id:'archived',name:'Archived, Student',roll_no:'S-OLD',department:'BSIT',section:'A',year_level:'1st Year',deleted_at:'2026-10-20'}];
  render();
  check(document.querySelector('.student-archive-panel').textContent.includes('Archived, Student'), 'Archived students are not retrievable in staff dashboard');
  check(!document.querySelector('.student-archive-panel button') && document.querySelector('.student-archive-panel').textContent.includes('Super admin can retrieve'), 'Teachers must request super admin retrieval');
  showModal({title:'Example',message:'Keyboard controls',cancelLabel:'Cancel'});
  check(document.activeElement.closest('[role="dialog"]'), 'Dialog did not receive focus');
  document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true}));
  check(!document.querySelector('[role="dialog"]'), 'Escape did not close the dialog');
  document.body.textContent = 'PASS: staff forms and directory search';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: staff forms and directory search")

    def test_txt_upload_all_parts_and_teacher_scores(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        sample = json.dumps((root / "files/exam_template.txt").read_text(encoding="utf-8"))
        checks = r"""
function check(condition, message) { if (!condition) throw new Error(message); }
function rejects(text, message) {
  let rejected = false;
  try { parseExamText(text); } catch (error) { rejected = true; }
  check(rejected, message);
}
(async () => {
  const parsed = parseExamText(SAMPLE);
  check(parsed.length === 9, 'Template item count');
  check(JSON.stringify(EXAM_PARTS.map(part => parsed.filter(q => q.part === part.part).length)) === '[2,2,2,3]', 'Wrong part counts');
  check(parsed[6].options.length === 5 && parsed[8].correct === 2, 'Shared matching bank');
  check(parsed[4].correct === 0 && parsed[5].correct === 1, 'True/False keys');
  check(parsed[2].alternatives[0] === 'CITY OF MANILA', 'Identification alternatives');
  check(parseExamText('\uFEFF' + SAMPLE.replace(/\n/g, '\r\n')).length === 9, 'Windows text encoding');
  check(parseExamText('Part III - True or False\nQuestion: Statement\nAnswer: False')[0].correct === 1, 'Roman part headings');
  check(parseExamText('Question: Old format\nA. One\nB. Two\nC. Three\nD. Four\nAnswer: B')[0].correct === 1, 'Existing MC format');
  check(parseExamText('Part 4 - Matching Type\nQuestion: Prompt\nA. One\nB. Two\nC. Three\nAnswer: C')[0].options.length === 3, 'Local matching choices');
  rejects('Part 3\nQuestion: Statement\nAnswer: Maybe', 'Invalid True/False accepted');
  rejects('Part 4\nChoices:\nA. One\nB. Two\nQuestion: Prompt\nAnswer: C', 'Unknown match accepted');
  rejects('Question: Missing answer\nA. One\nB. Two\nC. Three\nD. Four', 'Missing key accepted');
  rejects('Part 5\nQuestion: Unknown\nAnswer: A', 'Unknown part accepted');
  rejects('', 'Empty TXT accepted');
  rejects('Part 4\nChoices:\nA. One\nB. Two', 'Unused matching bank accepted');
  state.currentUser = {role: 'teacher', name: 'Teacher', departments: ['BSIT']};
  startCreateExam();
  await importQuestions(new File([SAMPLE], 'questions.txt', {type: 'text/plain'}));
  check(state.draft.questions.length === 9, 'Upload left a blank question or omitted an item');
  check(document.querySelector('#bulkQuestionsFile')?.accept.includes('.txt'), 'TXT picker absent');
  check(!document.querySelector('#bulkQuestions'), 'Paste interface still present');
  check(document.querySelectorAll('.qcard').length === 9, 'Editor count mismatch');
  check(document.querySelector('a[download]')?.getAttribute('href') === 'exam_template.txt', 'Template link missing');
  const saved = state.draft.questions;
  check(document.querySelector('.qnum').textContent.includes('2 POINTS') && document.querySelector('.builder-header p').textContent.includes('2 points'), 'Builder did not display the fixed points per question');
  await importQuestions(new File(['Part 3\nQuestion: Missing key'], 'invalid.txt'));
  check(state.errorMsg.includes('Line') && state.draft.questions === saved, 'Invalid upload changed the draft');
  await importQuestions(new File([SAMPLE], 'invalid.csv'));
  check(state.errorMsg.includes('.txt') && state.draft.questions === saved, 'Wrong extension accepted');
  const one = 'Part 3\nQuestion: Statement\nAnswer: False';
  const utf16 = new Uint8Array(2 + one.length * 2); utf16[0] = 255; utf16[1] = 254;
  for (let i = 0; i < one.length; i++) utf16[2 + i * 2] = one.charCodeAt(i);
  await importQuestions(new File([utf16], 'windows.txt'));
  check(state.draft.questions.length === 1 && state.draft.questions[0].type === 'true_false', 'UTF-16 or replacement count failed');
  setPart(state.draft.questions[0].id, 4);
  check(state.draft.questions[0].type === 'matching', 'Part 4 editor switch');
  setPart(state.draft.questions[0].id, 3);
  check(JSON.stringify(state.draft.questions[0].options) === '["True","False"]', 'Part 3 editor switch');
  state.exams = [{id: 'test-exam', title: 'Test', questionCount: 9}]; state.adminResultsExamId = 'test-exam';
  const result = {id: 'result', examId: 'test-exam', examTitle: 'Test', name: 'Student', rollNo: 'ID', score: 7, total: 9, percent: 77.8, timeTakenSec: 5, submittedAt: '2026-01-01', review: []};
  state.currentExamResults = [result];
  const results = renderAdminResults();
  check(results.includes('7 / 9') && results.includes('77.8%') && results.includes('Passed') && !results.includes('Percentile'), 'Teacher result percentage or status is missing');
  state.adminReviewResult = result;
  check(renderAdminResultReview().includes('77.8%') && renderAdminResultReview().includes('Passed'), 'Teacher review is missing percentage or pass status');
  state.adminReviewResult = {...result, review:[{text:'Item one',isCorrect:true,pointsAwarded:2,pointsPossible:2,options:[],chosen:null,correct:null}]};
  check(renderAdminResultReview().includes('Correct · 2 / 2 points'), 'Teacher review did not show awarded points for each question');
  state.teachers = [{id: 'teacher', name: 'Teacher', username: 'teacher', department: 'BSIT', rating_score: 77.8}];
  check(!renderTeacherManagement().includes('77.8%') && !renderTeacherManagement().includes('Student rating'), 'Teacher rating remains');
  state.currentUser = {role: 'teacher', name: 'Teacher', departments: ['BSIT']};
  await importQuestions(new File([SAMPLE], 'publish.txt'));
  Object.assign(state.draft, {title: 'All parts', subject: 'Test', targetGroups: [{department:'BSIT',yearLevels:['1st Year'],sections:['A']}]});
  let published = null;
  apiRequest = async (method, path, body) => { if (method === 'POST') published = body; return []; };
  await saveExam();
  check(published?.questions.length === 9, 'Publish changed item count');
  check(published.questions[4].type === 'true_false' && published.questions[6].type === 'matching', 'Publish changed question types');
  document.body.textContent = 'PASS: TXT upload and teacher scores';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
""".replace("SAMPLE", sample)
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: TXT upload and teacher scores")

    def test_activity_studio_without_overview_and_with_part_filters(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value, message) { if (!value) throw new Error(message); }
  function input(id, value) {
    const field = document.getElementById(id); field.value = value;
    field.dispatchEvent(new Event('input', {bubbles:true}));
  }
  state.currentUser = {role:'teacher',name:'Teacher',departments:['BSIT']};
  startCreateExam();
  check(document.querySelectorAll('.builder-main>section').length === 3, 'Builder sections missing');
  check(!document.querySelector('.builder-overview') && !document.querySelector('#builderSummary') && !document.querySelector('.overview-readiness'), 'Activity overview panel is still displayed');
  check(document.querySelectorAll('[data-publish-activity]').length === 1, 'Publish action is missing or duplicated');
  input('activityTitle', '<b>Weekly quiz</b>'); input('activitySubject', 'Computing'); input('activityDuration', '25');
  check(state.draft.title === '<b>Weekly quiz</b>' && state.draft.subject === 'Computing' && state.draft.duration === 25, 'Activity details were not saved in the draft');
  const subjectField = document.querySelector('#activitySubject');
  subjectField.focus(); subjectField.setSelectionRange(3, 3);
  input('activityTitle', '<b>Weekly quiz</b>');
  check(document.activeElement === subjectField && subjectField.selectionStart === 3, 'Editing details disrupted field focus or cursor');
  const quiz = document.querySelector('[name="builderActivityType"][value="quiz"]');
  quiz.checked = true; quiz.dispatchEvent(new Event('change', {bubbles:true}));
  check(state.draft.activityType === 'quiz', 'Activity type did not update');
  setTargetGroupDepartment(0, 'BSIT');
  setTargetGroupSelection(0, 'yearLevels', '1st Year', true);
  setTargetGroupSelection(0, 'yearLevels', '2nd Year', true);
  for (const year of ['1st Year','2nd Year']) {
    setTargetYearSection(0, year, 'A', true); setTargetYearSection(0, year, 'B', true);
  }
  check(targetGroupSections(state.draft.targetGroups[0], '1st Year').length + targetGroupSections(state.draft.targetGroups[0], '2nd Year').length === 4, 'Target classes were not stored');
  const first = state.draft.questions[0].id;
  setQuestionType(first, 'true_false'); setQText(first, 'A computer follows instructions.');
  check(document.querySelector('[data-question-status]').textContent === 'Ready', 'Question readiness did not update');
  filterBuilderQuestions('matching');
  check(document.querySelector('#builderQuestionEmpty').hidden === false && document.querySelector('.qcard').hidden, 'Empty part filter missing');
  addQuestion();
  const added = state.draft.questions[1];
  check(added.type === 'matching' && added.part === 4, 'New question ignored selected part');
  check(document.querySelectorAll('.qcard:not([hidden])').length === 1 && document.querySelector('[data-part-count="matching"]').textContent === '1', 'Question filter/count not preserved after adding');
  check(document.activeElement.tagName === 'TEXTAREA', 'Added question was not focused');
  check(document.querySelectorAll('[data-question-status]:not(.ready)').length === 1, 'Incomplete question status was not shown');
  setQText(added.id, 'CPU');
  ['Processes instructions', 'Displays images', 'Prints documents', 'Stores files'].forEach((value, index) => setOption(added.id, index, value));
  check(document.querySelectorAll('[data-question-status].ready').length === 2, 'Answer changes did not update question readiness');
  filterBuilderQuestions('all');
  check(document.querySelectorAll('.qcard:not([hidden])').length === 2, 'All filter did not restore questions');
  for (const year of ['1st Year','2nd Year']) setTargetYearSection(0, year, 'B', false);
  check(targetGroupSections(state.draft.targetGroups[0], '1st Year').length + targetGroupSections(state.draft.targetGroups[0], '2nd Year').length === 2, 'Removed target selections were not saved');
  let payload, finishPublish, publishCount = 0;
  apiRequest = async (method, path, body) => {
    if (method === 'POST') { payload = body; publishCount++; await new Promise(resolve => { finishPublish = resolve; }); }
    return [];
  };
  const saving = saveExam();
  await saveExam();
  check(publishCount === 1 && [...document.querySelectorAll('[data-publish-activity]')].every(button => button.disabled), 'Repeated publishing was allowed');
  finishPublish(); await saving;
  check(payload.activityType === 'quiz' && payload.duration === 25 && payload.targetClasses.length === 2 && payload.questions.length === 2, 'Redesigned builder changed publishing payload');
  document.body.textContent = 'PASS: activity studio without overview';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: activity studio without overview")

    def test_year_specific_target_sections_preserve_distinct_recipients(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        options = "window.ARALHUB_SCHOOL_OPTIONS={departments:['BSIT'],section:['A','B','C','D'],sections_by_department_and_year:{BSIT:{'1st Year':['A','B','C'],'2nd Year':['A','B','C','D']}}};"
        checks = r"""
(async () => {
  function check(value, message) { if (!value) throw new Error(message); }
  state.currentUser = {role:'teacher', name:'Teacher', departments:['BSIT']};
  startCreateExam(); setTargetGroupDepartment(0, 'BSIT');
  setTargetGroupSelection(0, 'yearLevels', '1st Year', true);
  setTargetGroupSelection(0, 'yearLevels', '2nd Year', true);
  check(document.querySelectorAll('[data-target-year="1st Year"] input').length === 3, 'First year has incorrect sections');
  check(document.querySelectorAll('[data-target-year="2nd Year"] input').length === 4, 'Second year has incorrect sections');
  check(document.querySelector('[data-target-year="1st Year"]').textContent.includes('BSIT 1-C') && document.querySelector('[data-target-year="2nd Year"]').textContent.includes('BSIT 2-D'), 'Class labels do not identify their year');
  document.querySelector('#target-0-year-0-section-2').click();
  document.querySelector('#target-0-year-1-section-3').click();
  setTargetYearSection(0, '1st Year', 'D', true);
  check(JSON.stringify(targetGroupSections(state.draft.targetGroups[0], '1st Year')) === '["C"]', 'First year accepted second-year section D');
  Object.assign(state.draft, {title:'Year-specific assessment', subject:'Computing', questions:[{...blankQuestion('true_false'), text:'A computer follows instructions.'}]});
  render();
  let payload;
  apiRequest = async (method, path, body) => { if (method === 'POST') payload = body; return []; };
  await saveExam();
  const expected = [{department:'BSIT',yearLevel:'1st Year',section:'C'},{department:'BSIT',yearLevel:'2nd Year',section:'D'}];
  check(JSON.stringify(payload.targetClasses) === JSON.stringify(expected), 'Publishing crossed sections between years');
  apiRequest = async () => ({title:'Year-specific assessment',subject:'Computing',duration:30,targetClasses:expected,questions:[{type:'true_false',part:3,text:'Statement',options:['True','False'],correct:0}]});
  await startEditExam('existing');
  check(document.querySelectorAll('[data-target-class]').length === 1 && document.querySelector('#target-0-year-0-section-2').checked && document.querySelector('#target-0-year-1-section-3').checked, 'Editing lost distinct year selections');
  setTargetGroupSelection(0, 'yearLevels', '1st Year', false);
  setTargetGroupSelection(0, 'yearLevels', '1st Year', true);
  check(targetGroupSections(state.draft.targetGroups[0], '1st Year').length === 0 && document.querySelector('#target-0-year-1-section-3').checked, 'Year deselection changed another year or restored stale selections');
  document.body.textContent = 'PASS: year-specific class selections';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        self.run_browser_check(options + "\n" + helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: year-specific class selections")

    def test_target_class_builder_results_and_filtered_exports(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value, message) { if (!value) throw new Error(message); }
  const targets = [{department:'BSIT',yearLevel:'2nd Year',section:'A'}, {department:'BSCRIM',yearLevel:'1st Year',section:'B'}];
  state.currentUser = {role:'teacher',name:'Teacher',departments:['BSIT']};
  startCreateExam();
  check(document.querySelectorAll('[data-target-class]').length === 1, 'Initial class row missing');
  state.currentUser = {role:'teacher',name:'Teacher',departments:['BSIT']};
  startCreateExam();
  check(document.querySelector('#target-0-department option[value="BSN"]'), 'Teacher cannot select a department outside their account assignment');
  Object.assign(state.draft, {title:'Shared Mathematics',subject:'Mathematics'});
  Object.assign(state.draft.questions[0], {text:'2+2?',options:['4','5','6','7'],correct:0});
  let published;
  apiRequest = async (method, path, body) => { if (method === 'POST' || method === 'PUT') published = body; return []; };
  await saveExam(); check(!published && state.errorMsg.includes('at least one year level and section'), 'Incomplete class published');
  const choose = (id,value) => { const field=document.getElementById(id); field.value=value; field.dispatchEvent(new Event('change')); };
  const select = (id, checked=true) => { const field=document.getElementById(id); field.checked=checked; field.dispatchEvent(new Event('change')); };
  choose('target-0-department','BSIT');
  select('target-0-year-1'); select('target-0-year-2');
  for (const year of [1,2]) { select(`target-0-year-${year}-section-0`); select(`target-0-year-${year}-section-1`); }
  document.querySelector('#addTargetGroup').click();
  check(document.activeElement.id === 'target-1-department', 'New row focus missing');
  choose('target-1-department','BSIT'); select('target-1-year-1'); select('target-1-year-1-section-0');
  await saveExam(); check(!published && state.errorMsg.includes('selected more than once'), 'Duplicate target class published');
  choose('target-1-department','BSCRIM'); select('target-1-year-1',false);
  select('target-1-year-0'); select('target-1-year-0-section-1');
  await saveExam();
  const expandedTargets = [
    {department:'BSIT',yearLevel:'2nd Year',section:'A'},
    {department:'BSIT',yearLevel:'2nd Year',section:'B'},
    {department:'BSIT',yearLevel:'3rd Year',section:'A'},
    {department:'BSIT',yearLevel:'3rd Year',section:'B'},
    {department:'BSCRIM',yearLevel:'1st Year',section:'B'}
  ];
  check(JSON.stringify(published.targetClasses) === JSON.stringify(expandedTargets), 'Multiple years and sections were not expanded into exact target classes: ' + JSON.stringify(published.targetClasses));
  check(!('yearLevel' in published) && !('sectionScope' in published), 'Global year/section mixed with target classes');
  apiRequest = async () => ({title:'Shared Mathematics',subject:'Mathematics',duration:30,targetClasses:expandedTargets,questions:[{text:'2+2?',options:['4','5','6','7'],correct:0}]});
  await startEditExam('exam');
  check(document.querySelector('#target-0-year-1').checked && document.querySelector('#target-0-year-2').checked && document.querySelector('#target-0-year-1-section-0').checked && document.querySelector('#target-0-year-2-section-1').checked && document.querySelector('#target-1-department').value === 'BSCRIM', 'Editing lost grouped year and section selections');
  removeTargetGroup(0);
  check(state.draft.targetGroups.length === 1 && document.querySelector('#target-0-department').value === 'BSCRIM', 'Removing a department changed another target group');
  check(document.activeElement.id === 'target-0-department', 'Remaining row lost focus');
  state.exams = [{id:'exam',title:'Shared Mathematics',subject:'Mathematics',questionCount:1,targetClasses:targets}];
  state.adminResultsExamId = 'exam';
  state.students = [
    {roll_no:'S-001',department:'BSIT',year_level:'2nd Year',section:'A'},
    {roll_no:'S-003',department:'BSIT',year_level:'2nd Year',section:'A'},
    {roll_no:'S-004',department:'BSCRIM',year_level:'1st Year',section:'B'}
  ];
  state.currentExamResults = [
    {id:'r1',name:'Sample, One',rollNo:'S-001',examId:'exam',examTitle:'Shared Mathematics',department:'BSIT',yearLevel:'2nd Year',section:'A',score:1,total:1,timeTakenSec:60,submittedAt:'2026-10-20T08:00:00'},
    {id:'r2',name:'Sample, Two',rollNo:'S-002',examId:'exam',examTitle:'Shared Mathematics',department:'BSIT',yearLevel:'1st Year',section:'A',score:0,total:1,timeTakenSec:60,submittedAt:'2026-10-20T08:00:00'}
  ];
  setView('adminResults');
  check(document.querySelector('#resultsDownloadHeading') && document.querySelectorAll('.results-download-panel button').length === 1, 'Single report download action is missing');
  check(document.querySelector('#resultsExportFormat') && document.querySelector('#resultsExportScope'), 'Report format and scope selectors are missing');
  const counts = [...document.querySelectorAll('.class-progress tbody tr:first-child td')].slice(1,4).map(cell => cell.textContent);
  check(JSON.stringify(counts) === '["2","1","1"]', 'Class roster/submission counts incorrect');
  check(!document.querySelector('.class-progress button') && document.querySelectorAll('.class-progress th').length === 4, 'Class submissions should only display counts');
  setResultsDeptFilter('BSIT'); setResultsYearFilter('2nd Year'); setResultsSectionFilter('A');
  check(document.querySelector('#resultsExportScope option').textContent.includes('BSIT · 2nd Year · Section A'), 'Selected report scope is not shown in the system');
  check(document.querySelectorAll('.results-table tbody tr').length === 1 && document.querySelector('.results-table tbody').textContent.includes('S-001'), 'Year filter mixed section A of different years');
  const sheets = [], excelFiles = [];
  window.XLSX = {utils:{
    book_new:()=>({}),
    json_to_sheet:rows=>({rows, A1:{}, A2:{}, K2:{}}),
    encode_cell:cell=>String.fromCharCode(65 + cell.c) + (cell.r + 1),
    encode_range:range=>`A1:K${range.e.r + 1}`,
    book_append_sheet:(book,sheet,name)=>sheets.push({sheet,name})
  },writeFile:(workbook,filename)=>excelFiles.push({workbook,filename})};
  downloadResultsExcel();
  check(sheets.length === 1 && sheets[0].sheet.rows.length === 1 && sheets[0].sheet.rows[0]['ID Number'] === 'S-001', 'Excel ignored year/class filters');
  check(excelFiles[0].filename.includes('BSIT_2nd_Year_Section_A'), 'Filtered Excel filename omitted selected class');
  check(sheets[0].sheet.A1.s.font.bold && sheets[0].sheet.A1.s.fill.fgColor.rgb === '182B45', 'Excel header design is missing');
  check(sheets[0].sheet.A2.s.fill.fgColor.rgb === 'FFFFFF' && sheets[0].sheet['!autofilter'].ref === 'A1:K2', 'Excel table formatting or filter is missing');
  downloadResultsExcel(true);
  check(sheets.length === 3 && sheets.slice(1).reduce((count, sheet) => count + sheet.sheet.rows.length, 0) === 2, 'Download all Excel did not include every class');
  check(excelFiles[1].filename.includes('All_departments_All_years_All_sections'), 'All Excel filename did not identify its scope');
  const pdfTables = [];
  const pdfFiles = [];
  window.jspdf = {jsPDF:function(){return new Proxy({internal:{pageSize:{getWidth:()=>297,getHeight:()=>210}},lastAutoTable:{finalY:100},autoTable:table=>pdfTables.push(table),save:filename=>pdfFiles.push(filename)}, {get:(object,key)=>key in object ? object[key] : ()=>{}});}};
  downloadResultsPdf();
  check(pdfTables.length === 1 && pdfTables[0].body.length === 1 && pdfTables[0].body[0][2] === 'S-001', 'PDF ignored year/class filters');
  check(pdfFiles[0].includes('BSIT_2nd_Year_Section_A'), 'Filtered PDF filename omitted selected class');
  downloadResultsPdf(true);
  check(pdfTables.length === 3 && pdfTables.slice(1).reduce((count, table) => count + table.body.length, 0) === 2, 'Download all PDF did not include every class');
  check(pdfFiles[1].includes('All_departments_All_years_All_sections'), 'All PDF filename did not identify its scope');
  document.querySelector('#resultsExportFormat').value = 'excel';
  document.querySelector('#resultsExportScope').value = 'all';
  downloadSelectedResults();
  check(excelFiles.length === 3 && document.querySelector('#resultsExportStatus').textContent.includes('All departments') && document.querySelector('#resultsExportStatus').textContent.includes('Excel'), 'Single download action did not apply selected format and all-results scope');
  document.body.textContent = 'PASS: target classes, results, and exports';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        school_options = """window.ARALHUB_SCHOOL_OPTIONS = {
          departments:['BSIT','BSCRIM','BEED','BSHM','BSN'],
          section:['A','B','C'], year_level:['1st Year','2nd Year','3rd Year','4th Year'],
          sections_by_department:{BSIT:['A','B','C'],BSCRIM:['A','B'],BEED:['A','B','C'],BSHM:['A','B','C'],BSN:['A','B','C']}
        };"""
        self.run_browser_check(school_options + "\n" + helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: target classes, results, and exports")

    def test_excel_report_all_department_year_section_combinations(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
try {
  function check(value, message) { if (!value) throw new Error(message); }
  const departments = ['BSIT', 'BSCRIM', 'BEED', 'BSHM', 'BSN'];
  const years = ['1st Year', '2nd Year', '3rd Year', '4th Year'];
  const sections = ['A', 'B', 'C', 'D', 'E', 'F'];
  const results = [];
  const targets = [];
  let index = 0;
  for (const department of departments) {
    for (const yearLevel of years) {
      for (const section of sections) {
        const target = {department, yearLevel, section};
        targets.push(target);
        results.push({
          id: `r${index}`, name: `Student ${index}, Example`, rollNo: `ID-${index}`,
          examId: 'exam', examTitle: 'All Classes', department, yearLevel, section,
          score: index % 5, total: 5, timeTakenSec: 60, submittedAt: '2026-10-20T08:00:00'
        });
        index++;
      }
    }
  }
  results.push({
    ...results[0], id: 'extra', name: 'Additional, Student', rollNo: 'ID-EXTRA'
  });
  state.currentUser = {role:'teacher',name:'Teacher',departments};
  state.exams = [{id:'exam',title:'All Classes',activityType:'quiz',questionCount:5,targetClasses:targets}];
  state.adminResultsExamId = 'exam';
  state.currentExamResults = results;
  state.students = [{roll_no:'NOT-SUBMITTED',department:'BSIT',year_level:'1st Year',section:'A'}];
  const html = renderAdminResults();
  for (const department of departments) check(html.includes(`value="${department}"`), `Missing department filter ${department}`);
  for (const year of years) check(html.includes(`value="${year}"`), `Missing year filter ${year}`);
  for (const section of sections) check(html.includes(`value="${section}"`), `Missing section filter ${section}`);
  const downloads = [];
  const columnName = column => String.fromCharCode(65 + column);
  window.XLSX = {utils:{
    book_new:()=>({sheets:[]}),
    json_to_sheet:rows=>{
      const sheet = {rows};
      const headers = Object.keys(rows[0] || {});
      headers.forEach((header, column) => { sheet[`${columnName(column)}1`] = {}; });
      rows.forEach((row, rowIndex) => Object.values(row).forEach((value, column) => {
        sheet[`${columnName(column)}${rowIndex + 2}`] = {};
      }));
      return sheet;
    },
    encode_cell:cell=>`${columnName(cell.c)}${cell.r + 1}`,
    encode_range:range=>`A1:K${range.e.r + 1}`,
    book_append_sheet:(book,sheet,name)=>book.sheets.push({sheet,name})
  },writeFile:book=>downloads.push(book.sheets)};
  let tested = 0;
  for (const department of departments) {
    for (const yearLevel of years) {
      for (const section of sections) {
        state.resultsDeptFilter = department;
        state.resultsYearFilter = yearLevel;
        state.resultsSectionFilter = section;
        const filtered = filteredExamResults();
        const isFirstClass = department === departments[0] && yearLevel === years[0] && section === sections[0];
        check(filtered.length === (isFirstClass ? 2 : 1), `Incorrect filtered submission count for ${department}/${yearLevel}/${section}`);
        check(filtered.every(row => row.department === department && row.yearLevel === yearLevel && row.section === section), `Filter mixed classes for ${department}/${yearLevel}/${section}`);
        downloadResultsExcel();
        const sheets = downloads[downloads.length - 1];
        check(sheets.length === 1, `Expected one Excel sheet for ${department}/${yearLevel}/${section}`);
        check(sheets[0].sheet.rows.length === filtered.length, `Excel row count mismatch for ${department}/${yearLevel}/${section}`);
        check(sheets[0].sheet.rows.every(row => row.Department === department && row['Year Level'] === yearLevel && row.Section === `${department}-${section}`), `Excel contains a different class in ${department}/${yearLevel}/${section}`);
        check(!sheets[0].sheet.rows.some(row => row['ID Number'] === 'NOT-SUBMITTED'), 'Unsubmitted student was exported');
        tested++;
      }
    }
  }
  check(tested === 120 && downloads.length === 120, 'Not all 120 class reports were generated');
  document.body.textContent = `PASS: ${tested} department/year/section Excel reports`;
} catch (error) { document.body.textContent = 'FAIL: ' + error.message; }
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: 120 department/year/section Excel reports")

    def test_student_question_controls_and_score_only_receipt(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => { try {
  function check(condition, message) { if (!condition) throw new Error(message); }
  state.currentUser = {name: 'Student', rollNo: 'ID'};
  const questions = [
    {id: 'tf', type: 'true_false', part: 3, text: 'Statement', options: ['True', 'False']},
    {id: 'match', type: 'matching', part: 4, text: 'Prompt', options: ['One', 'Two', 'Three', 'Four', 'Five']},
    {id: 'identify', type: 'identification', part: 2, text: 'Capital city', options: []},
  ];
  state.runtime = {exam: {questions, duration: 10, title: 'Test', activityType: 'exam'}, answers: {}, currentIdx: 0, secondsLeft: 600};
  state.view = 'takeExam'; render();
  check(document.querySelector('.question-count').textContent.includes('1 point'), 'Student question did not display its point value');
  check(document.querySelectorAll('.option').length === 2, 'True/False must show two choices');
  check(document.querySelector('.part-label').textContent.includes('Part 3'), 'Wrong True/False label');
  document.querySelectorAll('.option')[1].click();
  check(state.runtime.answers.tf === 1, 'False answer was not selected');
  jumpTo(1);
  check(document.querySelectorAll('.option').length === 5, 'Matching bank was truncated');
  check(document.querySelector('.part-label').textContent.includes('Part 4'), 'Wrong matching label');
  document.querySelectorAll('.option')[4].click();
  check(state.runtime.answers.match === 4, 'Fifth matching choice was not recorded');
  jumpTo(2);
  const answer = document.querySelector('#identification-answer');
  answer.value = 'Manila'; answer.dispatchEvent(new Event('input'));
  check(document.querySelector('[role="progressbar"]').getAttribute('aria-valuenow') === '3', 'Identification progress did not update');
  answer.value = '   '; answer.dispatchEvent(new Event('input'));
  check(document.querySelector('[role="progressbar"]').getAttribute('aria-valuenow') === '2', 'Blank answer counted as completed');
  check(document.querySelector('[data-answer-count]').textContent === '2 of 3 answered', 'Answer count is stale');
  state.lastResult = {score: 2, total: 2, percent: 100, examTitle: 'Test', timeTakenSec: 5, review: [
    {...questions[0], chosen: 1, correct: 1, isCorrect: true},
    {...questions[1], chosen: 0, correct: 4, isCorrect: false},
  ]};
  state.view = 'studentResult'; render();
  check(document.querySelector('#app').textContent.includes('Your work is saved.'), 'Submission receipt is missing');
  check(document.querySelector('#app').textContent.includes('100.0%') && document.querySelector('.grade-status.passed').textContent === 'Passed', 'Passing score was not shown');
  state.lastResult = {score: 24, total: 50, percent: 48, examTitle: 'Test', timeTakenSec: 5};
  render();
  check(document.querySelector('#app').textContent.includes('48.0%') && document.querySelector('.grade-status.failed').textContent === 'Failed', 'Below-half score was not marked Failed');
  state.lastResult = {score: 25, total: 50, percent: 50, examTitle: 'Test', timeTakenSec: 5};
  render();
  check(document.querySelector('.grade-status.passed').textContent === 'Passed', 'Exactly-half score should pass');
  state.lastResult = {id:'own-result',score:24,total:50,percent:48,examTitle:'Test',timeTakenSec:5};
  apiRequest = async (method, path) => {
    check(method === 'GET' && path === '/api/results/own-result/review', 'Student review requested wrong result');
    return {review:[{text:'Statement',type:'true_false',options:['True','False'],chosen:1,correct:1,isCorrect:true,pointsAwarded:1,pointsPossible:1}]};
  };
  await openStudentResultReview();
  check(document.querySelector('.review-item')?.textContent.includes('Your answer: False'), 'Student could not review their own answer');
  check(document.querySelector('.review-item')?.textContent.includes('1 / 1 points'), 'Student answer review omitted points');
  check(document.querySelector('.review-item')?.textContent.includes('Correct answer: False'), 'Student review omitted the correct answer');
  check(typeof viewPastResult === 'undefined', 'Student answer review handler remains accessible');
  state.exams = [{id:'submitted',title:'Completed exam',activityType:'exam',questionCount:2,duration:10}];
  state.myResults = [{id:'saved',examId:'submitted',score:2,total:2}];
  setView('studentHome');
  check(!document.querySelector('#app').textContent.includes('View result'), 'Completed card still offers a review');
  check(!document.querySelector('.exam-row button'), 'Completed card still offers access to its exam');
  document.body.textContent = 'PASS: student question controls';
} catch (error) { document.body.textContent = 'FAIL: ' + error.message; } })();
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: student question controls")

    def test_student_home_shows_only_assessments_and_fits_viewport(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        css = json.dumps((root / "files/css/modern.css").read_text(encoding="utf-8"))
        checks = r"""
try {
  function check(condition, message) { if (!condition) throw new Error(message); }
  const style=document.createElement('style'); style.textContent=STYLES; document.head.append(style);
  state.currentUser={name:'Student Example',rollNo:'S1',department:'BSIT'};
  state.exams=Array.from({length:12},(_,index)=>({
    id:`exam-${index}`,title:`Assessment ${index+1}`,subject:'Computing',activityType:'exam',
    questionCount:10,duration:30,yearLevel:'1st Year',sectionScope:'A'
  }));
  state.myResults=[];
  setView('studentHome');
  check(document.querySelectorAll('.sidebar-nav .nav-item').length===2 && document.querySelector('.sidebar-nav').textContent.includes('Lecture materials'), 'Student assessment and lecture navigation missing');
  check(document.querySelector('.sidebar-nav').textContent.includes('My assessments') && !document.querySelector('.sidebar-nav').textContent.includes('Overview'), 'Student navigation is not assessments-only');
  check(!document.querySelector('#overview') && document.querySelector('#activities h1').textContent==='My assessments', 'Overview content is still displayed');
  check(document.body.classList.contains('student-home-page'), 'Student home viewport layout is not enabled');
  check(document.documentElement.scrollHeight<=innerHeight+1 && document.documentElement.scrollWidth<=innerWidth+1, 'Student workspace requires page scrolling');
  check(document.querySelector('.exam-list').scrollHeight>document.querySelector('.exam-list').clientHeight, 'Long assessment list does not scroll inside its panel');
  document.body.textContent='PASS: student assessment workspace fits viewport';
} catch(error) { document.body.textContent='FAIL: '+error.message; }
""".replace("STYLES", css)
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: student assessment workspace fits viewport")

    def test_live_results_preserve_filters_and_recover_without_stale_navigation(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value, message) { if (!value) throw new Error(message); }
  const timers = new Map(), nativeTimeout = window.setTimeout, nativeClear = window.clearTimeout;
  let timerId = -1;
  window.setTimeout = (fn, delay, ...args) => {
    if (delay === 3000 || delay === 6000) { const id=timerId--; timers.set(id,{fn,delay}); return id; }
    return nativeTimeout(fn,delay,...args);
  };
  window.clearTimeout = id => { if (timers.has(id)) timers.delete(id); else nativeClear(id); };
  async function poll() {
    check(timers.size === 1, 'Live results scheduled duplicate polls');
    const [id,timer] = [...timers][0]; timers.delete(id); await timer.fn();
  }
  state.currentUser = {role:'teacher',name:'Teacher',departments:['BSIT']};
  state.exams = [{id:'exam',title:'Live exam',questionCount:10,targetClasses:[{department:'BSIT',yearLevel:'1st Year',section:'A'}]}];
  const first = {id:'r1',examId:'exam',examTitle:'Live exam',name:'Student One',rollNo:'S1',department:'BSIT',yearLevel:'1st Year',section:'A',score:8,total:10,timeTakenSec:60,submittedAt:'2026-10-20T08:00:00'};
  let rows = [first], fail = false, resultRequests = 0, rosterRequests = 0;
  apiRequest = async (method,path) => {
    if (fail) throw new Error('Offline');
    if (path.endsWith('/activity')) return [];
    if (path.startsWith('/api/results?')) resultRequests++;
    if (path === '/api/students/managed') rosterRequests++;
    return path.startsWith('/api/results?') ? JSON.parse(JSON.stringify(rows)) : [{roll_no:'S1',department:'BSIT',year_level:'1st Year',section:'A'}];
  };
  await openAdminResults('exam');
  check(document.querySelectorAll('.results-table tbody tr').length === 1 && timers.size === 1, 'Initial results did not start live updates');
  const requestsBeforeManualRefresh = resultRequests;
  document.querySelector('#refreshResultsButton').click();
  await new Promise(resolve => nativeTimeout(resolve, 0));
  check(resultRequests === requestsBeforeManualRefresh + 1, 'Manual refresh did not request fresh results');
  check(!document.querySelector('#refreshResultsButton').disabled, 'Refresh button remained disabled after results loaded');
  state.resultsDeptFilter='BSIT'; state.resultsYearFilter='1st Year'; state.resultsSectionFilter='A'; render();
  document.querySelector('#classProgressPanel').open=false;
  const focused = document.querySelector('.admin-results-page select'); focused.focus();
  rows.push({...first,id:'r2',rollNo:'S2',name:'Student Two'});
  await poll();
  check(document.querySelectorAll('.results-table tbody tr').length === 2, 'New submission did not appear automatically');
  check(state.resultsDeptFilter === 'BSIT' && state.resultsYearFilter === '1st Year' && state.resultsSectionFilter === 'A', 'Live update reset filters');
  check(!document.querySelector('#classProgressPanel').open && document.activeElement.id === focused.id, 'Live update reset panel or filter focus');
  const table = document.querySelector('.results-table');
  await poll(); check(document.querySelector('.results-table') === table, 'Unchanged results were unnecessarily rebuilt');
  fail=true; await poll();
  check(state.currentExamResults.length === 2 && !document.querySelector('#resultsLiveError').hidden, 'Connection failure erased results or hid status');
  check([...timers.values()][0].delay === 6000, 'Reconnect did not back off');
  fail=false; await poll();
  check(document.querySelector('#resultsLiveError').hidden && document.querySelector('#resultsLiveStatus').textContent.startsWith('Live'), 'Live results did not recover');
  const rosterBeforeResultsRefresh = JSON.stringify(state.students);
  apiRequest = async (method,path) => {
    if (path.startsWith('/api/results?')) return JSON.parse(JSON.stringify(rows));
    if (path === '/api/students/managed') throw new Error('Teacher or admin access required.');
    throw new Error('Unexpected request');
  };
  const lastSuccessfulRefresh = state.resultsLastUpdated;
  await refreshAdminResults();
  check(state.resultsLastUpdated >= lastSuccessfulRefresh, 'Results did not refresh');
  check(document.querySelector('#resultsLiveError').hidden && document.querySelector('#resultsLiveStatus').textContent.startsWith('Live'), 'Roster permission error remained visible on results');
  check(JSON.stringify(state.students) === rosterBeforeResultsRefresh && rosterRequests === 0, 'Results refresh unexpectedly requested the student roster');
  showModal({title:'Review action',message:'Confirm',cancelLabel:'Cancel'});
  check(timers.size === 0, 'Live update ran while a confirmation was open');
  closeModal(); check(timers.size === 1, 'Live updates did not resume after closing a confirmation');
  let finish;
  apiRequest = (method,path) => path.startsWith('/api/results?') ? new Promise(resolve => {finish=resolve;}) : Promise.resolve([]);
  const pending=refreshAdminResults();
  setView('adminHome'); finish([]); await pending;
  check(state.view === 'adminHome' && !document.querySelector('.admin-results-page'), 'Late response reopened results after navigation');
  stopResultsLiveUpdates(); window.setTimeout=nativeTimeout; window.clearTimeout=nativeClear;
  document.body.textContent='PASS: live results lifecycle';
})().catch(error => { document.body.textContent='FAIL: '+error.message; });
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: live results lifecycle")

    def test_dashboard_live_counts_update_without_recent_submissions(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  const exam={id:'live',title:'Live exam',subject:'Computing',activityType:'exam',questionCount:1,attempts:0};
  let attempts=0;
  state.currentUser={role:'teacher',name:'Teacher',departments:['BSIT']};
  apiRequest=async(method,path)=>{
    if(path==='/api/results')throw new Error('Dashboard must not request recent submissions');
    return path.startsWith('/api/exams')?[{...exam,attempts}]:[];
  };
  await goAdminHome();
  check(!state.connError && !document.querySelector('.live-submissions') && !document.querySelector('#recentSubmissionsHeading'),'Recent submissions remain on the dashboard');
  attempts=1; await refreshTeacherDashboard();
  check(state.exams[0].attempts===1,'Activity attempt count was not synchronized');
  apiRequest=async()=>{throw new Error('Offline');}; await refreshTeacherDashboard();
  check(state.exams[0].attempts===1 && document.querySelector('[data-teacher-network]').textContent==='Check connection','Offline refresh erased counts or hid connection status');
  apiRequest=async()=>[exam];
  await refreshTeacherDashboard(); check(!state.dashboardLiveError,'Dashboard did not reconnect');
  let finish;
  apiRequest=()=>new Promise(resolve=>{finish=resolve;});
  const pending=refreshTeacherDashboard(); startCreateExam(); finish([]); await pending;
  check(state.view==='createExam','Late dashboard response navigated away from the builder');
  document.body.textContent='PASS: live teacher counts without recent submissions';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: live teacher counts without recent submissions")

    def test_returned_assessment_syncs_to_student_and_restores_answers(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  const exam={id:'returned',title:'Returned quiz',activityType:'quiz',duration:15,questionCount:1,returned:true};
  state.currentUser={role:'student',name:'Student',rollNo:'RETURN-001'};
  state.lastResult={id:'original',examId:exam.id,examTitle:exam.title,score:0,total:2};
  state.myResults=[state.lastResult]; setView('studentResult');
  apiRequest=async(method,path)=>path.startsWith('/api/exams')?[exam]:[];
  await refreshStudentWorkspace();
  check(state.view==='studentHome' && !state.lastResult && !state.myResults.length,'Teacher return did not unlock student receipt');
  check(document.querySelector('.badge').textContent.includes('Returned') && document.querySelector('.exam-row button').textContent.includes('Continue'),'Returned assessment was not identified');
  apiRequest=async()=>({...exam,questions:[{id:'q1',type:'multiple_choice',text:'Question',options:['A','B']}],returnedAttempt:{returnId:'ret1',answers:{q1:1}}});
  await beginExam(exam.id);
  check(state.runtime.answers.q1===1 && state.runtime.secondsLeft===900,'Returned answers or fresh time allowance were not restored');
  check(document.querySelector('#answer-q1-1').checked,'Restored answer was not selected');
  selectAnswer('q1',0);
  const deadline=state.runtime.deadlineAt, submission=state.runtime.submissionId;
  clearInterval(state.runtime.timerId); state.savedAttempt=readSavedAttempt(); state.runtime=null;
  await resumeSavedAttempt(exam.id);
  check(state.runtime.answers.q1===0 && state.runtime.deadlineAt===deadline && state.runtime.submissionId===submission,'Reloading a returned assessment reset edited answers or its timer');
  clearInterval(state.runtime.timerId); clearSavedAttempt(); state.runtime=null;
  document.body.textContent='PASS: returned assessment student sync';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: returned assessment student sync")

    def test_focus_submission_retries_saved_answers_after_connection_failure(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value,message){if(!value)throw new Error(message);}
  state.currentUser={role:'student',name:'Student',rollNo:'RETRY-FOCUS'};
  state.runtime={exam:{id:'retry',title:'Retry test',activityType:'exam',duration:15,questions:[{id:'q1',type:'multiple_choice',text:'Question',options:['A','B']}]},answers:{q1:1},currentIdx:0,secondsLeft:900,deadlineAt:Date.now()+900000,submissionId:'stable-retry'};
  setView('takeExam'); let calls=[];
  apiRequest=async(method,path,payload)=>{if(path.endsWith('/activity'))return {ok:true};calls.push({...payload}); if(calls.length===1)throw new Error('Offline'); return {id:'saved',examId:'retry',examTitle:'Retry test',score:2,total:2,percent:100};};
  await submitExam(true,'tab_switch');
  check(state.runtime.pendingSubmission==='tab_switch' && readSavedAttempt().pendingSubmission==='tab_switch','Failed automatic submission lost its reason or recovery state');
  selectAnswer('q1',0); check(state.runtime.answers.q1===1,'Pending automatic submission still accepts changes');
  await submitExam(true,state.runtime.pendingSubmission);
  check(state.view==='studentResult' && !state.runtime && !readSavedAttempt() && !document.querySelector('[role="dialog"]'),'Successful retry did not clear pending work and error modal');
  check(calls.length===2 && calls.every(call=>call.submissionId==='stable-retry' && call.autoSubmitted && call.submitReason==='tab_switch' && call.answers.q1===1),'Retry duplicated or altered the attempt');
  document.body.textContent='PASS: automatic submission offline recovery';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: automatic submission offline recovery")

    def test_reopen_result_offers_sign_in_when_staff_session_expires(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  state.currentUser={role:'teacher',name:'Teacher'};
  state.currentExamResults=[{id:'result-1',activityType:'exam'}];
  let shown;
  showModal=options=>{shown=options;};
  apiRequest=async()=>{const error=new Error('Your staff session has expired. Sign in again to return this submission.'); error.status=401; throw error;};
  reopenAdminResult('result-1');
  await shown.onConfirm('ID-001');
  check(shown.title==='Staff session expired' && shown.confirmLabel==='Sign in again', 'Expired session did not offer a sign-in action');
  check(shown.message.includes('has not been changed'), 'Expired session message did not confirm the submission is unchanged');
  document.body.textContent='PASS: expired staff session recovery prompt';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: expired staff session recovery prompt")

    def test_exam_numbers_and_controls_stay_inside_the_viewport(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        css = json.dumps((root / "files/css/modern.css").read_text(encoding="utf-8"))
        checks = r"""
try {
  function check(value, message) { if (!value) throw new Error(message); }
  const style=document.createElement('style'); style.textContent=STYLES; document.head.append(style);
  state.currentUser={role:'student',name:'Student',rollNo:'S1'};
  state.runtime={exam:{title:'Viewport exam',subject:'Computing',activityType:'exam',duration:60,questions:Array.from({length:100},(_,i)=>({id:'q'+i,type:'identification',part:2,text:i===0 ? 'A long question.\n'.repeat(80) : 'Question '+(i+1),options:[]}))},answers:{},currentIdx:0,secondsLeft:3600};
  setView('takeExam');
  check(document.querySelector('#examNext').classList.contains('btn') && !document.querySelector('#examNext').classList.contains('secondary'), 'Next button is not using the filled primary style');
  const questionNumberStyle=getComputedStyle(document.querySelector('.qnav button'));
  check(parseFloat(questionNumberStyle.height)>=48 && parseFloat(questionNumberStyle.fontSize)>=14, 'Question numbers are not large enough');
  const within = element => {const box=element.getBoundingClientRect(); return box.top>=-1 && box.bottom<=innerHeight+1 && box.left>=-1 && box.right<=innerWidth+1;};
  check(within(document.querySelector('.question-navigator')) && within(document.querySelector('.exam-nav-row')), 'Question numbers or controls are outside the viewport');
  check(document.documentElement.scrollHeight<=innerHeight+1 && document.documentElement.scrollWidth<=innerWidth+1, 'Exam requires page scrolling');
  const panel=document.querySelector('.question-block'); panel.scrollTop=100;
  check(panel.scrollTop>0, 'Long question content was clipped');
  check(!document.querySelector('.question-page-controls'), 'Question number pagination is still displayed');
  check(document.querySelectorAll('.qnav button').length===100 && document.getElementById('question-nav-99'), 'Not all question numbers are shown in one navigator');
  const index=31;
  document.getElementById('question-nav-'+index).click();
  check(state.runtime.currentIdx===index && document.querySelector('.question-block').scrollTop===0, 'Question number opened the wrong question');
  jumpTo(99);
  check(document.getElementById('question-nav-99').getAttribute('aria-current')==='step', 'Last question was not visible in the navigator');
  const answer=document.querySelector('#identification-answer'); answer.value='Manila'; answer.dispatchEvent(new Event('input'));
  check(document.getElementById('question-nav-99').classList.contains('answered'), 'Answer marker used the page offset instead of question index');
  check(within(document.querySelector('.question-navigator')) && within(document.querySelector('#examSubmit')), 'Last question moved controls off screen');
  state.runtime=null;
  document.body.textContent='PASS: viewport exam navigation';
} catch(error) {document.body.textContent='FAIL: '+error.message;}
""".replace("STYLES", css)
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: viewport exam navigation")

    def test_exam_question_numbers_restart_for_each_randomized_part(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        student = re.findall(r"<script>(.*?)</script>", (root / "files/index.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
try {
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const types=['multiple_choice','identification','true_false','matching'];
  const questions=types.flatMap((type,partIndex)=>Array.from({length:30},(_,i)=>({
    id:`p${partIndex+1}-q${i+1}`,part:partIndex+1,type,text:`Part ${partIndex+1} question ${i+1}`,
    options:type==='identification'?[]:['A','B','C','D']
  })));
  state.currentUser={role:'student',name:'Student',rollNo:'PART-NUMBERS'};
  state.runtime={exam:{title:'Four-part exam',subject:'Computing',activityType:'exam',duration:60,questions},answers:{},currentIdx:0,secondsLeft:3600};
  setView('takeExam');
  check(document.querySelector('.question-count').textContent.startsWith('Question 1 of 30'), 'Part 1 did not start at question 1 of 30');
  for(let part=0;part<4;part++) {
    const buttons=[...document.querySelectorAll('.qnav-part')][part].querySelectorAll('button');
    check(buttons.length===30 && buttons[0].textContent.trim()==='1' && buttons[29].textContent.trim()==='30','Part '+(part+1)+' navigator did not number questions 1-30');
    check(buttons[0].getAttribute('aria-label').includes('Part '+(part+1)),'Navigator question was not identified by its part');
    const start=part*30;
    jumpTo(start+29);
    check(document.querySelector('.question-count').textContent.startsWith('Question 30 of 30'), 'Part '+(part+1)+' did not end at question 30 of 30');
    if(part<3) {
      jumpTo(start+30);
      check(document.querySelector('.question-count').textContent.startsWith('Question 1 of 30'), 'Part '+(part+2)+' did not restart at question 1 of 30');
    }
  }
  state.runtime=null;
  document.body.textContent='PASS: per-part exam numbering';
} catch(error) {document.body.textContent='FAIL: '+error.message;}
"""
        self.run_browser_check(helpers + "\n" + student + "\n" + checks, "PASS: per-part exam numbering")

    def test_workspace_navigation_search_and_filters(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  state.currentUser = {role:'teacher',name:'Teacher Test',departments:['BSIT']};
  state.exams = [
    {id:'e1',title:'Programming Fundamentals',subject:'Programming',activityType:'exam',questionCount:20,duration:30,attempts:2,departments:['BSIT'],sectionScope:'ALL'},
    {id:'e2',title:'Network Basics',subject:'Networking',activityType:'quiz',questionCount:10,duration:15,attempts:1,departments:['BSIT'],sectionScope:'A'},
  ];
  setView('adminHome');
  check(document.querySelector('.workspace') && document.querySelector('#mainContent'), 'Workspace frame missing');
  check(document.querySelectorAll('.sidebar-nav .nav-item').length === 4 && document.querySelector('.sidebar-nav').textContent.includes('Lecture materials') && !document.querySelector('.sidebar-nav').textContent.includes('Notifications'), 'Teacher sidebar navigation is incorrect');
  check(!document.querySelector('#overview') && !document.querySelector('.sidebar-nav').textContent.includes('Overview'), 'Teacher overview is still displayed');
  check(!document.querySelector('#students') && document.querySelector('.breadcrumb strong').textContent === 'My assessments', 'Teacher home did not open assessments');
  document.querySelector('[aria-label="Manage Networking"]').click();
  const input = document.querySelector('#activitySearch');
  input.value='network'; input.dispatchEvent(new Event('input'));
  check(document.querySelectorAll('.exam-row:not([hidden])').length === 1, 'Subject search failed');
  check(document.querySelector('.exam-row:not([hidden])').dataset.activity === 'quiz', 'Search matched wrong assessment');
  document.querySelectorAll('.activity-tabs button')[2].click();
  check(document.querySelectorAll('.exam-row:not([hidden])').length === 1, 'Quiz filter failed inside selected subject');
  document.querySelectorAll('.activity-tabs button')[1].click();
  check(document.querySelectorAll('.exam-row:not([hidden])').length === 0 && !document.querySelector('#activityNoMatches').hidden, 'Exam filter failed inside selected subject');
  document.querySelectorAll('.activity-tabs button')[0].click();
  input.value=''; input.dispatchEvent(new Event('input'));
  check(document.querySelectorAll('.exam-row:not([hidden])').length === 1, 'All activities filter failed inside selected subject');
  await openWorkspaceSection('students');
  check(document.querySelector('.sidebar-nav [aria-current="page"]').textContent.includes('Students'), 'Navigation state did not update');
  check(document.querySelector('#students'), 'Student section is missing');
  check(!document.querySelector('#activities') && document.querySelector('.breadcrumb strong').textContent === 'Students', 'Student navigation displayed assessments');
  document.body.textContent='PASS: navigation and activity search';
})().catch(error => { document.body.textContent='FAIL: '+error.message; });
"""
        self.run_browser_check(helpers + "\n" + teacher + "\n" + checks, "PASS: navigation and activity search")

    def test_reference_teacher_dashboard_groups_and_manages_real_subjects(self):
        root = Path(__file__).parent
        helpers = (root / "files/js/common.js").read_text(encoding="utf-8")
        parser = (root / "files/js/exam-format.js").read_text(encoding="utf-8")
        teacher = re.findall(r"<script>(.*?)</script>", (root / "files/administrator.html").read_text(encoding="utf-8"), re.S)[-1]
        checks = r"""
(async () => {
  function check(value, message) { if (!value) throw new Error(message); }
  state.currentUser={role:'teacher',name:'Teacher <Test>',departments:['BSIT']};
  const exams=[
    {id:'one',subject:'Programming',title:'Loops',activityType:'exam',questionCount:10,duration:30,attempts:1,createdAt:'2026-10-19T08:00:00'},
    {id:'two',subject:' programming ',title:'Programming Quiz',activityType:'quiz',questionCount:5,duration:15,attempts:2},
    {id:'three',subject:'Networking',title:'Programming a network',activityType:'exam',questionCount:12,duration:30,attempts:0},
  ];
  state.exams=exams; setView('adminHome');
  check(document.querySelector('.sidebar') && !document.querySelector('.teacher-topbar'), 'Teacher sidebar was not restored');
  check(document.querySelector('.teacher-welcome h1').textContent.includes('Teacher <Test>') && !document.querySelector('.teacher-welcome h1 test'), 'Welcome name was missing or unescaped');
  check(document.querySelectorAll('.teacher-subject-card').length===2 && document.querySelector('.teacher-summary-card strong').textContent==='2', 'Subjects were not grouped from real activities');
  check(!document.querySelector('#activities') && !document.querySelector('.teacher-activities-panel'), 'Assessments are shown outside a managed subject');
  document.querySelector('[aria-label="Manage Programming"]').click();
  check(document.querySelectorAll('.exam-row:not([hidden])').length===2 && !document.querySelector('.teacher-subjects') && document.querySelector('.teacher-activities-panel .eyebrow').textContent==='YOUR ASSESSMENTS', 'Manage did not open the subject assessments');
  check([...document.querySelectorAll('.exam-row:not([hidden])')].every(card=>card.dataset.subject==='programming'), 'Subject management matched a different subject through its title');
  startCreateExam();
  check(state.draft.subject==='Programming' && document.querySelector('#activitySubject').value==='Programming', 'New activity lost the managed subject');
  apiRequest=async (method,path)=>path.startsWith('/api/exams') ? exams : [];
  await openWorkspaceSection('activities');
  check(!state.selectedTeacherSubject && document.querySelectorAll('.exam-row:not([hidden])').length===0 && document.querySelector('.teacher-subjects') && !document.querySelector('.teacher-activities-panel'), 'Dashboard did not return to the subject list');
  Object.defineProperty(navigator,'onLine',{configurable:true,value:false}); window.dispatchEvent(new Event('offline'));
  check(document.querySelector('[data-teacher-network]').textContent==='Check connection', 'Network card did not respond to connection changes');
  delete navigator.onLine; window.dispatchEvent(new Event('online'));
  state.exams=[]; render();
  check(document.querySelector('.teacher-subject-empty') && document.querySelector('.teacher-summary-card strong').textContent==='0', 'Empty dashboard displays fake subjects');
  document.body.textContent='PASS: reference teacher dashboard';
})().catch(error=>{document.body.textContent='FAIL: '+error.message;});
"""
        self.run_browser_check(helpers + "\n" + parser + "\n" + teacher + "\n" + checks, "PASS: reference teacher dashboard")

    def test_browser_retries_only_safe_submissions(self):
        edge = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"
        if not edge.is_file():
            self.skipTest("Microsoft Edge is not installed")
        helper = (Path(__file__).parent / "files/js/common.js").read_text(encoding="utf-8")
        checks = r"""
const delays = [];
window.setTimeout = (callback, delay) => { delays.push(delay); callback(); return 0; };
const calls = [];
let steps = [];
window.fetch = async (path, options) => {
  calls.push({path, options});
  const next = steps.shift();
  if (next instanceof Error) throw next;
  return {ok: next.status === 200, status: next.status,
    json: async () => { if (next.invalidJson) throw new SyntaxError(); return next.data || {error: 'busy'}; }};
};
function check(condition, message) { if (!condition) throw new Error(message); }
async function scenario(sequence, method, path, body, expectedCalls, shouldPass) {
  _csrfToken = 'synthetic-csrf-token';
  calls.length = 0; delays.length = 0; steps = sequence;
  let passed = false;
  try { await apiRequest(method, path, body); passed = true; } catch (error) {}
  check(passed === shouldPass, 'Unexpected request outcome');
  check(calls.length === expectedCalls, 'Unexpected number of attempts: ' + calls.length);
  check(calls.every(call => call.options.body === calls[0].options.body), 'Retry changed the submission');
  check(delays.length === expectedCalls - 1, 'Missing retry delay');
  delays.forEach((delay, i) => check(delay >= 1000 * (2 ** i) && delay < 1000 * (2 ** i) + 500, 'Bad backoff'));
}
(async () => {
  const body = {submissionId: 'browser-test-attempt', answers: {q1: 1}};
  await scenario([{status: 503}, {status: 200, data: {id: 'saved'}}], 'POST', '/api/results', body, 2, true);
  await scenario([new TypeError('connection lost'), {status: 200, data: {id: 'saved'}}], 'POST', '/api/results', body, 2, true);
  await scenario(Array.from({length: 4}, () => ({status: 503})), 'POST', '/api/results', body, 4, false);
  await scenario([{status: 401}], 'POST', '/api/results', body, 1, false);
  await scenario([{status: 409}], 'POST', '/api/results', body, 1, false);
  await scenario([{status: 500}], 'POST', '/api/results', body, 1, false);
  await scenario([{status: 503}], 'POST', '/api/results', {answers: {}}, 1, false);
  await scenario([{status: 503}], 'POST', '/api/exams', body, 1, false);
  await scenario([{status: 200, invalidJson: true}, {status: 200, data: {id: 'saved'}}], 'POST', '/api/results', body, 2, true);
  document.body.textContent = 'PASS: 9 browser retry scenarios';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        with tempfile.TemporaryDirectory(prefix="aralhub-browser-") as directory:
            root = Path(directory)
            page = root / "retry-test.html"
            page.write_text("<!doctype html><body>RUNNING<script>" + helper + "\n" + checks + "</script>", encoding="utf-8")
            result = subprocess.run(
                [str(edge), "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                 "--disable-background-networking", f"--user-data-dir={root / 'profile'}",
                 "--virtual-time-budget=1000", "--dump-dom", page.as_uri()],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            self.assertIn("<body>PASS: 9 browser retry scenarios", result.stdout, result.stdout[-2000:] + result.stderr[-1000:])

    def test_browser_fetches_and_refreshes_django_csrf_tokens(self):
        helper = (Path(__file__).parent / "files/js/common.js").read_text(encoding="utf-8")
        checks = r"""
(async () => {
  function check(condition, message) { if (!condition) throw new Error(message); }
  let handshakes = 0, forbidden = false;
  const writes = [];
  window.fetch = async (path, options) => {
    if (path === '/api/csrf') {
      handshakes++;
      return {ok:true,status:200,json:async () => ({csrfToken:'token-'+handshakes})};
    }
    if (options.method !== 'GET') writes.push({path,token:options.headers['X-CSRFToken']});
    return {ok:!forbidden,status:forbidden?403:200,json:async () => ({ok:true})};
  };
  await apiRequest('GET', '/api/exams');
  check(handshakes === 0, 'Read-only request fetched a security token');
  await Promise.all([apiRequest('POST','/api/exams',{}), apiRequest('PUT','/api/exams/example',{})]);
  check(handshakes === 1 && writes.every(write => write.token === 'token-1'), 'Concurrent writes did not share a token handshake');
  await apiRequest('POST','/api/admin/login',{});
  await apiRequest('DELETE','/api/exams/example');
  check(handshakes === 2 && writes.at(-1).token === 'token-2', 'Token was not refreshed after login');
  forbidden = true;
  await apiRequest('POST','/api/results',{}).catch(() => {});
  forbidden = false;
  await apiRequest('POST','/api/results',{});
  check(handshakes === 3 && writes.at(-1).token === 'token-3', 'Rejected token was reused');
  document.body.textContent = 'PASS: Django browser security tokens';
})().catch(error => { document.body.textContent = 'FAIL: ' + error.message; });
"""
        self.run_browser_check(helper + "\n" + checks, "PASS: Django browser security tokens")


if __name__ == "__main__":
    unittest.main()
