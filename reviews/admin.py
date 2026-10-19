from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group, User

from .admin_site import admin_site
from .models import Professor, Report, Review, School, Tag, Vote

try:
    admin_site.register(User, UserAdmin)
except admin.sites.AlreadyRegistered:
    pass
try:
    admin_site.register(Group, GroupAdmin)
except admin.sites.AlreadyRegistered:
    pass


@admin.register(School, site=admin_site)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "city", "region", "type", "website"]
    list_filter = ["city", "region", "type"]
    search_fields = ["name", "short_name", "city"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Tag, site=admin_site)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name"]


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    fields = ["course", "overall", "difficulty", "status", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(Professor, site=admin_site)
class ProfessorAdmin(admin.ModelAdmin):
    list_display = ["full_name", "school", "department", "title", "status", "created_at"]
    list_filter = ["status", "school", "department"]
    search_fields = ["first_name", "last_name", "department"]
    actions = ["approve_selected"]

    @admin.action(description="Одобрить выбранных преподавателей")
    def approve_selected(self, request, queryset):
        queryset.update(status="approved")

    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = "ФИО"


@admin.register(Review, site=admin_site)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["professor", "course", "overall", "difficulty", "grade", "status", "reported", "created_at"]
    list_filter = ["status", "overall", "grade"]
    search_fields = ["comment", "course", "professor__first_name", "professor__last_name"]
    actions = ["approve_selected", "reject_selected"]
    filter_horizontal = ["tags"]

    @admin.action(description="Одобрить выбранные отзывы")
    def approve_selected(self, request, queryset):
        queryset.update(status="approved")

    @admin.action(description="Отклонить выбранные отзывы")
    def reject_selected(self, request, queryset):
        queryset.update(status="rejected")


@admin.register(Vote, site=admin_site)
class VoteAdmin(admin.ModelAdmin):
    list_display = ["review", "user", "helpful", "created_at"]
    list_filter = ["helpful"]


@admin.register(Report, site=admin_site)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["review", "user", "created_at"]
