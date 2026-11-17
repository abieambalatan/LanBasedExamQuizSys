"""Django Superadmin for the existing teacher and student records."""

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Count, Q
from django.db.models.expressions import RawSQL
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from django.urls import path, reverse

from .models import Teacher, Student, Exam, SchoolOption, timestamp
from .constants import MAX_SECTIONS_PER_DEPARTMENT, YEAR_LEVELS
from .security import generate_password_hash
from .school_options import option_values, sections_for_all_departments, sections_in_use
from .accounts import RETIRED_PREFIX, permanently_delete_account


class PasswordFields(forms.ModelForm):
    password1 = forms.CharField(label="New password", required=False, min_length=4, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), help_text="Leave both password fields blank to keep the existing password.")
    password2 = forms.CharField(label="Confirm new password", required=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1", "") != cleaned.get("password2", ""):
            self.add_error("password2", "The passwords do not match.")
        return cleaned


class TeacherForm(PasswordFields):
    departments = forms.MultipleChoiceField(
        choices=[],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Teacher
        fields = ["name", "username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        departments = option_values(SchoolOption.DEPARTMENT)
        self.fields["departments"].choices = [(department, department) for department in departments]
        if not self.instance._state.adding:
            with connection.cursor() as cursor:
                cursor.execute("SELECT department FROM teacher_departments WHERE teacher_username=%s ORDER BY department", [self.instance.username])
                self.fields["departments"].initial = [row[0] for row in cursor.fetchall()] or [self.instance.department]

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if username.startswith(RETIRED_PREFIX):
            raise forms.ValidationError("This username prefix is reserved. Choose another username.")
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError("This username belongs to a Django administrator. Choose a separate teacher username.")
        return username

    def clean(self):
        cleaned = super().clean()
        if self.instance._state.adding and not cleaned.get("password1"):
            self.add_error("password1", "Set a password for this new teacher.")
        return cleaned


class StudentPasswordForm(PasswordFields):
    class Meta:
        model = Student
        fields = []


class ArchiveFilter(admin.SimpleListFilter):
    title = "account status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [("active", "Active"), ("archived", "Deleted / inactive")]

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(deleted_at__isnull=True)
        if self.value() == "archived":
            return queryset.filter(deleted_at__isnull=False)
        return queryset


class StudentArchiveFilter(admin.SimpleListFilter):
    title = "account status"
    parameter_name = "student_status"

    def lookups(self, request, model_admin):
        return [("active", "Active"), ("archived", "Deleted / inactive")]

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(deleted_at__isnull=True)
        if self.value() == "archived":
            return queryset.filter(deleted_at__isnull=False)
        return queryset


class SchoolOptionFilter(admin.SimpleListFilter):
    category = None

    def lookups(self, request, model_admin):
        return [(value, value) for value in option_values(self.category)]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(**{f"{self.parameter_name}__exact": self.value()})
        return queryset


class DepartmentFilter(SchoolOptionFilter):
    title = "department"
    parameter_name = "department"
    category = SchoolOption.DEPARTMENT


class TeacherDepartmentFilter(DepartmentFilter):
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                Q(department=self.value())
                | Q(username__in=RawSQL(
                    "SELECT teacher_username FROM teacher_departments WHERE department=%s",
                    [self.value()],
                ))
            )
        return queryset


class YearLevelFilter(SchoolOptionFilter):
    title = "year level"
    parameter_name = "year_level"

    def lookups(self, request, model_admin):
        return [(value, value) for value in YEAR_LEVELS]


class SectionFilter(SchoolOptionFilter):
    title = "section"
    parameter_name = "section"

    def lookups(self, request, model_admin):
        return [(value, value) for value in sections_for_all_departments()]


class SchoolOptionForm(forms.ModelForm):
    value = forms.CharField(
        max_length=20,
        help_text="Enter the department name or code.",
    )
    section_count = forms.IntegerField(
        label="Default section count",
        min_value=1,
        max_value=MAX_SECTIONS_PER_DEPARTMENT,
        help_text=f"Used for year levels without an override below. Sections run from A onward (1–{MAX_SECTIONS_PER_DEPARTMENT}).",
    )
    year_1_sections = forms.IntegerField(label="1st Year sections", required=False, min_value=1, max_value=26, help_text="For example, 3 means A, B, C. Blank uses the default.")
    year_2_sections = forms.IntegerField(label="2nd Year sections", required=False, min_value=1, max_value=26, help_text="For example, 4 means A, B, C, D. Blank uses the default.")
    year_3_sections = forms.IntegerField(label="3rd Year sections", required=False, min_value=1, max_value=26, help_text="Blank uses the default section count.")
    year_4_sections = forms.IntegerField(label="4th Year sections", required=False, min_value=1, max_value=26, help_text="Blank uses the default section count.")

    class Meta:
        model = SchoolOption
        fields = ["value", "section_count", "position"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for index, year in enumerate(YEAR_LEVELS, 1):
            self.fields[f"year_{index}_sections"].initial = self.instance.year_section_counts.get(year)

    def clean_value(self):
        value = self.cleaned_data["value"].strip()
        value = value.upper()
        if not value:
            raise forms.ValidationError("Enter a value.")
        duplicates = SchoolOption.objects.filter(category=SchoolOption.DEPARTMENT, value=value)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError("A department with this value already exists.")
        return value

    def clean(self):
        cleaned = super().clean()
        default = cleaned.get("section_count")
        if default is None:
            return cleaned
        counts = {}
        for index, year in enumerate(YEAR_LEVELS, 1):
            field = f"year_{index}_sections"
            override = cleaned.get(field)
            if override is not None:
                counts[year] = override
            previous = self.instance.year_section_counts.get(year, self.instance.section_count)
            current = override if override is not None else default
            if self.instance.pk and current < previous:
                removed = [chr(ord("A") + i) for i in range(current, previous)]
                used = sections_in_use(self.instance.value, removed, year)
                if used:
                    self.add_error(field if override is not None else "section_count", f"Cannot reduce {year}: existing records use {', '.join(used)}. Move those records first.")
        self.instance.year_section_counts = counts
        return cleaned

@admin.register(SchoolOption)
class SchoolOptionAdmin(admin.ModelAdmin):
    form = SchoolOptionForm
    list_display = ["value", "sections_by_year", "position", "usage_count"]
    search_fields = ["value"]
    ordering = ["position", "value"]
    actions = ["delete_unused_options"]
    fields = ["value", "position", "section_count", "year_1_sections", "year_2_sections", "year_3_sections", "year_4_sections", "usage_count"]
    readonly_fields = ["usage_count"]

    @admin.display(description="Sections by year level")
    def sections_by_year(self, obj):
        return " · ".join(f"{year}: {obj.year_section_counts.get(year, obj.section_count)}" for year in YEAR_LEVELS)

    @staticmethod
    def _references(category):
        return [
            ("students", "department"),
            ("teachers", "department"),
            ("teacher_departments", "department"),
            ("exams", "department"),
            ("results", "department"),
            ("exam_departments", "department"),
            ("exam_target_classes", "department"),
            ("portal_lectureclass", "department"),
        ]

    @classmethod
    def _usage_count(cls, option):
        with connection.cursor() as cursor:
            return sum(
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column}=%s",
                    [option.value],
                ).fetchone()[0]
                for table, column in cls._references(option.category)
            )

    @admin.display(description="Records using this value")
    def usage_count(self, obj):
        return self._usage_count(obj)

    @classmethod
    def _rename_references(cls, category, old_value, new_value):
        with connection.cursor() as cursor:
            for table, column in cls._references(category):
                key_columns = {
                    "teacher_departments": ("teacher_username",),
                    "exam_departments": ("exam_id",),
                    "exam_target_classes": ("exam_id", "year_level", "section"),
                    "portal_lectureclass": ("material_id", "year_level", "section"),
                }.get(table)
                if key_columns:
                    cursor.execute(
                        f"SELECT {', '.join(key_columns)} FROM {table} WHERE {column}=%s",
                        [old_value],
                    )
                    for key_values in cursor.fetchall():
                        key_filter = " AND ".join(f"{key}=%s" for key in key_columns)
                        key_values = list(key_values)
                        cursor.execute(
                            f"SELECT 1 FROM {table} WHERE {key_filter} AND {column}=%s",
                            [*key_values, new_value],
                        )
                        if cursor.fetchone():
                            cursor.execute(
                                f"DELETE FROM {table} WHERE {key_filter} AND {column}=%s",
                                [*key_values, old_value],
                            )
                        else:
                            cursor.execute(
                                f"UPDATE {table} SET {column}=%s WHERE {key_filter} AND {column}=%s",
                                [new_value, *key_values, old_value],
                            )
                    continue
                cursor.execute(
                    f"UPDATE {table} SET {column}=%s WHERE {column}=%s",
                    [new_value, old_value],
                )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.category = SchoolOption.DEPARTMENT
        if change:
            previous = SchoolOption.objects.get(pk=obj.pk)
            if previous.value != obj.value:
                self._rename_references(previous.category, previous.value, obj.value)
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if obj is None:
            return True
        return (
            self._usage_count(obj) == 0
            and SchoolOption.objects.filter(category=obj.category).count() > 1
        )

    @admin.action(description="Delete selected values that are not in use")
    def delete_unused_options(self, request, queryset):
        deletable = []
        protected = []
        selected = list(queryset)
        selected_per_category = {}
        for option in selected:
            selected_per_category[option.category] = selected_per_category.get(option.category, 0) + 1
        for option in selected:
            remaining = SchoolOption.objects.filter(category=option.category).count()
            if (
                self._usage_count(option)
                or remaining <= selected_per_category[option.category]
            ):
                protected.append(option.value)
            else:
                deletable.append(option.pk)
        if deletable:
            count, _ = queryset.model.objects.filter(pk__in=deletable).delete()
            self.message_user(request, f"Deleted {count} unused school value(s).", messages.SUCCESS)
        if protected:
            self.message_user(
                request,
                f"Kept {', '.join(protected)} because it is in use or is the last value in its category. Edit a value to rename it across existing records.",
                messages.ERROR,
            )


class AccountLifecycleAdmin:
    """Super admin deletion is permanent; teacher-deleted students can be retrieved."""

    def get_urls(self):
        name = self.model._meta.model_name
        return [path("<path:object_id>/account/<str:operation>/", self.admin_site.admin_view(self.account_action_view),
                     name=f"portal_{name}_account_action")] + super().get_urls()

    @admin.display(description="Account actions")
    def account_actions(self, obj):
        url = reverse(f"admin:portal_{self.model._meta.model_name}_account_action", args=[obj.pk, "delete"])
        delete_button = format_html('<a class="button" href="{}">DELETE permanently</a>', url)
        if obj.deleted_at:
            retrieve_url = reverse(f"admin:portal_{self.model._meta.model_name}_account_action", args=[obj.pk, "retrieve"])
            return format_html('{} <a class="button" href="{}">Retrieve account</a>', delete_button, retrieve_url)
        return delete_button

    def deletion_confirmation(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.POST.get("confirmation") == "DELETE":
            return None
        return TemplateResponse(request, "admin/portal/account_action.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta,
            "title": "Permanently delete selected accounts?", "queryset": queryset, "operation": "delete",
            "bulk_action": request.POST.get("action"),
            "error": "Type DELETE exactly to confirm." if request.POST.get("confirm_account_action") else "",
            "list_url": reverse(f"admin:portal_{self.model._meta.model_name}_changelist"),
        })

    def account_action_view(self, request, object_id, operation):
        obj = self.get_object(request, object_id)
        if obj is None or operation not in ("delete", "retrieve"):
            raise Http404
        if not request.user.is_superuser or not self.has_change_permission(request, obj):
            raise PermissionDenied
        list_url = reverse(f"admin:portal_{self.model._meta.model_name}_changelist")
        error = ""
        if request.method == "POST":
            if operation == "delete" and request.POST.get("confirmation") != "DELETE":
                error = "Type DELETE exactly to confirm. The account has not been changed."
            elif request.POST.get("confirm_account_action") == "yes":
                if operation == "delete":
                    with transaction.atomic():
                        self.log_deletions(request, [obj])
                        permanently_delete_account(self.model._meta.model_name, obj.pk)
                else:
                    self.model.objects.filter(pk=obj.pk).update(deleted_at=None)
                    self.log_change(request, obj, "Retrieved teacher-deleted account; sign-in restored.")
                self.message_user(request, "Account permanently deleted. It cannot be retrieved." if operation == "delete" else "Account retrieved. Sign-in is enabled again.", messages.SUCCESS)
                return HttpResponseRedirect(list_url)
        return TemplateResponse(request, "admin/portal/account_action.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta,
            "title": "Permanently delete account?" if operation == "delete" else "Retrieve account?",
            "queryset": [obj], "operation": operation, "error": error, "list_url": list_url,
        })


@admin.register(Teacher)
class TeacherAdmin(AccountLifecycleAdmin, admin.ModelAdmin):
    form = TeacherForm
    list_display = ["name", "username", "assigned_departments", "account_status", "created_at", "account_actions"]
    list_filter = [ArchiveFilter, TeacherDepartmentFilter]
    search_fields = ["name", "username"]
    fields = ["name", "username", "departments", "password1", "password2", "created_at", "account_status"]
    readonly_fields = ["created_at", "account_status"]
    actions = ["archive_teachers", "restore_teachers"]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (["username"] if obj else [])

    @admin.display(description="Departments", ordering="department")
    def assigned_departments(self, obj):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT department FROM teacher_departments WHERE teacher_username=%s ORDER BY department",
                [obj.username],
            )
            departments = [row[0] for row in cursor.fetchall()]
        return ", ".join(departments) or obj.department

    @admin.display(description="Status")
    def account_status(self, obj):
        return "Deleted / inactive" if obj.deleted_at else "Active"

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        departments = form.cleaned_data["departments"]
        obj.department = departments[0]
        if form.cleaned_data.get("password1"):
            obj.password_hash = generate_password_hash(form.cleaned_data["password1"])
        super().save_model(request, obj, form, change)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM teacher_departments WHERE teacher_username=%s", [obj.username])
            cursor.executemany("INSERT INTO teacher_departments (teacher_username, department) VALUES (%s,%s)", [(obj.username, department) for department in departments])

    @admin.action(description="DELETE selected teacher accounts permanently")
    def archive_teachers(self, request, queryset):
        confirmation = self.deletion_confirmation(request, queryset)
        if confirmation is not None:
            return confirmation
        count = 0
        with transaction.atomic():
            for teacher in list(queryset):
                self.log_deletions(request, [teacher])
                if permanently_delete_account("teacher", teacher.pk):
                    count += 1
        self.message_user(request, f"Permanently deleted {count} teacher account(s). They cannot be retrieved.", messages.SUCCESS)

    @admin.action(description="Retrieve selected teacher accounts")
    def restore_teachers(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        selected = queryset.filter(deleted_at__isnull=False)
        for teacher in selected:
            self.log_change(request, teacher, "Restored teacher account.")
        count = selected.update(deleted_at=None)
        self.message_user(request, f"Restored {count} teacher account(s).", messages.SUCCESS)


@admin.register(Student)
class StudentAdmin(AccountLifecycleAdmin, admin.ModelAdmin):
    form = StudentPasswordForm
    change_list_template = "admin/portal/student_change_list.html"
    list_display = ["name", "roll_no", "department", "section", "year_level", "account_status", "account_actions"]
    search_fields = ["name", "roll_no"]
    list_filter = [StudentArchiveFilter, DepartmentFilter, SectionFilter, YearLevelFilter]
    readonly_fields = ["name", "first_name", "last_name", "middle_initial", "roll_no", "department", "section", "year_level", "created_at", "deleted_at"]
    fields = readonly_fields + ["password1", "password2"]
    actions = ["archive_students", "restore_students"]

    @admin.display(description="Status")
    def account_status(self, obj):
        return f"Deleted / inactive ({obj.deleted_at})" if obj.deleted_at else "Active"

    @admin.action(description="DELETE selected student accounts permanently")
    def archive_students(self, request, queryset):
        confirmation = self.deletion_confirmation(request, queryset)
        if confirmation is not None:
            return confirmation
        count = 0
        with transaction.atomic():
            for student in list(queryset):
                self.log_deletions(request, [student])
                if permanently_delete_account("student", student.pk):
                    count += 1
        self.message_user(
            request,
            f"Permanently deleted {count} student account(s). They cannot be retrieved.",
            messages.SUCCESS,
        )

    @admin.action(description="Retrieve selected student accounts")
    def restore_students(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        selected = queryset.filter(deleted_at__isnull=False)
        count = selected.update(deleted_at=None)
        self.message_user(request, f"Restored {count} student account(s).", messages.SUCCESS)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        if not getattr(response, "context_data", None):
            return response
        counts = dict(self.get_queryset(request).values("department").annotate(total=Count("pk")).values_list("department", "total"))
        selected = request.GET.get("department__exact", request.GET.get("department", "ALL"))
        cards = []
        for department in ["ALL", *option_values(SchoolOption.DEPARTMENT)]:
            query = request.GET.copy()
            for key in ("p", "department", "department__exact"):
                query.pop(key, None)
            if department != "ALL":
                query["department__exact"] = department
            cards.append({
                "label": "All departments" if department == "ALL" else department,
                "count": sum(counts.values()) if department == "ALL" else counts.get(department, 0),
                "selected": selected == department,
                "url": "?" + query.urlencode(),
            })
        response.context_data["student_department_cards"] = cards
        return response

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("password1"):
            obj.password_hash = generate_password_hash(form.cleaned_data["password1"])
            obj.save(update_fields=["password_hash"])


class ReadOnlyAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Exam)
class ExamAdmin(ReadOnlyAdmin):
    list_display = ["title", "activity_type", "subject", "created_by", "department", "created_at"]
    search_fields = ["title", "subject", "created_by"]
    list_filter = ["activity_type", "department", "year_level"]
    fields = ["title", "activity_type", "subject", "created_by", "target_class_list", "duration", "created_at"]
    readonly_fields = fields

    @admin.display(description="Target classes")
    def target_class_list(self, obj):
        from .db import get_db
        from .targets import target_classes
        conn = get_db()
        try:
            exam = conn.execute("SELECT * FROM exams WHERE id=?", (obj.pk,)).fetchone()
            targets = target_classes(conn, exam)
        finally:
            conn.close()
        return format_html_join("", "<div>{} · {} · Section {}</div>",
                                ((item["department"], item["yearLevel"], item["section"]) for item in targets))
