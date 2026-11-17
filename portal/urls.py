"""The original frontend URLs, backed by Django views."""

from django.urls import path
from . import views, learning, authentication, monitoring
from .http import endpoint


urlpatterns = [
    path("login", endpoint(GET=views.login_page), name="login"),
    path("login.html", endpoint(GET=views.login_page), name="login-html"),
    path("student", endpoint(GET=authentication.require_page_role("student")(views.student_page)), name="student-dashboard"),
    path("teacher", endpoint(GET=authentication.require_page_role("teacher")(views.teacher_page)), name="teacher-dashboard"),
    path("api/auth/login", endpoint(POST=authentication.login), name="shared-login"),
    path("api/auth/session", endpoint(GET=authentication.session_account), name="session-account"),
    path("api/learning/materials", endpoint(GET=learning.list_materials, POST=learning.create_material), name="lecture-materials"),
    path("api/learning/materials/<str:material_id>", endpoint(DELETE=learning.delete_material), name="delete-lecture-material"),
    path("api/learning/materials/<str:material_id>/submissions", endpoint(GET=learning.list_submissions, POST=learning.submit_file), name="activity-file-submissions"),
    path("api/learning/files/<str:kind>/<str:file_id>", endpoint(GET=learning.serve_file), name="learning-file"),
    path("api/csrf", endpoint(GET=views.csrf_token), name="csrf-token"),
    path('', endpoint(GET=views.index), name='index'),
    path('admin', endpoint(GET=views.legacy_admin_page), name='legacy-admin-page'),
    path('admin.html', endpoint(GET=views.legacy_admin_page), name='legacy-admin-page'),
    path('administrator', endpoint(GET=views.administrator_page), name='administrator-page'),
    path('administrator.html', endpoint(GET=views.administrator_page), name='administrator-page'),
    path('api/admin/login', endpoint(POST=views.admin_login), name='admin-login'),
    path('api/exams', endpoint(GET=views.list_exams, POST=views.create_exam), name='list-exams'),
    path('api/logout', endpoint(POST=views.logout), name='logout'),
    path('api/results', endpoint(POST=views.submit_result, GET=views.get_results), name='submit-result'),
    path('api/students/login', endpoint(POST=views.student_login), name='student-login'),
    path('api/students/managed', endpoint(GET=views.list_managed_students), name='list-managed-students'),
    path('api/students/archived', endpoint(GET=views.list_archived_students), name='list-archived-students'),
    path('api/students/signup', endpoint(POST=views.student_signup), name='student-signup'),
    path('api/students/<str:student_id>', endpoint(DELETE=views.archive_student), name='archive-student'),
    path('api/students/<str:student_id>/restore', endpoint(POST=views.restore_student), name='restore-student'),
    path('api/teachers', endpoint(GET=views.list_teachers), name='list-teachers'),
    path('api/teachers/archived', endpoint(GET=views.list_archived_teachers), name='list-archived-teachers'),
    path('api/teachers/available', endpoint(GET=views.available_teachers), name='available-teachers'),
    path('api/exams/<str:exam_id>', endpoint(GET=views.get_exam_admin, PUT=views.update_exam, DELETE=views.delete_exam), name='get-exam-admin'),
    path('api/exams/<str:exam_id>/take', endpoint(GET=views.take_exam), name='take-exam'),
    path('api/exams/<str:exam_id>/activity', endpoint(GET=monitoring.get_activity, POST=monitoring.save_activity), name='assessment-activity'),
    path('api/exams/<str:exam_id>/activity/<str:activity_id>', endpoint(GET=monitoring.get_activity), name='assessment-activity-detail'),
    path('api/results/<str:result_id>', endpoint(DELETE=views.reopen_result), name='reopen-result'),
    path('api/results/<str:result_id>/review', endpoint(GET=views.get_result_review), name='get-result-review'),
    path('api/students/<str:student_id>/reset-password', endpoint(POST=views.reset_student_password), name='reset-student-password'),
    path('api/teachers/<str:teacher_id>', endpoint(DELETE=views.delete_teacher), name='delete-teacher'),
    path('api/teachers/<str:teacher_id>/reset-password', endpoint(POST=views.reset_teacher_password), name='reset-teacher-password'),
    path('api/teachers/<str:teacher_id>/restore', endpoint(POST=views.restore_teacher), name='restore-teacher'),
    path("<path:path>", endpoint(GET=views.serve_frontend), name="frontend-file"),
]
