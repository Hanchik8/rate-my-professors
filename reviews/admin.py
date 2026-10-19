from django.contrib import admin
from .models import School, Professor, Review, Tag, Vote, Report


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "city", "region", "type", "website"]
    list_filter = ["city", "region", "type"]
    search_fields = ["name", "short_name", "city"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name"]


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    fields = ["course", "overall", "difficulty", "status", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(Professor)
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


@admin.register(Review)
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


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ["review", "user", "helpful", "created_at"]
    list_filter = ["helpful"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["review", "user", "created_at"]
