import hashlib
import json
from pathlib import Path
import django
django.setup()
from django.db import connection
from django.core.management import call_command

def read(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()

def preserved():
    data = {}
    for table in ('students', 'teachers', 'exams', 'questions'):
        data[table] = read(f'SELECT * FROM {table} ORDER BY id' if table not in ('students', 'teachers') else f'SELECT * FROM {table} ORDER BY 1')
    data['answers'] = read('SELECT id,exam_id,roll_no,answers_json FROM results ORDER BY id')
    data['returned'] = []
    for rid, raw in read('SELECT id,snapshot FROM portal_submissionreturn ORDER BY id'):
        saved = json.loads(raw)
        for key in ('score','total','percent'):
            saved.pop(key, None)
        data['returned'].append((rid, saved))
    return hashlib.sha256(json.dumps(data,default=str,sort_keys=True).encode()).hexdigest()

before_hash = preserved()
before = read('SELECT id,score,total,percent FROM results ORDER BY id')
call_command('migrate', interactive=False, verbosity=1)
call_command('check')
after = read('SELECT id,score,total,percent FROM results ORDER BY id')
assert preserved() == before_hash, 'Unexpected account, exam, question or submitted-answer change'
assert len(before) == len(after), 'Submission count changed'
remaining = read("""SELECT COUNT(*) FROM results r JOIN exams e ON e.id=r.exam_id
 WHERE e.activity_type='exam' AND r.total=2*(SELECT COUNT(*) FROM questions q WHERE q.exam_id=e.id)
 AND EXISTS(SELECT 1 FROM questions q WHERE q.exam_id=e.id AND q.type IN ('true_false','matching'))""")[0][0]
report = dict(submissions=len(after), corrected_submissions=sum(a != b for a,b in zip(before,after)),
              accounts_assessments_questions_and_answers_preserved=True, backups_created=False,
              historical_original_totals_remaining=remaining,
              scoring={'exam':{'multiple_choice':2,'identification':2,'true_false':1,'matching':1},'quiz':1})
Path('reports/question_type_points_deployment.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
