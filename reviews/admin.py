from django.contrib import admin
from .models import AccountProfile, Professor, Report, Review, School, Tag, Vote


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "city", "region", "kind", "code"]
    list_filter = ["region", "kind", "city"]
    search_fields = ["name", "name_ky", "name_en", "short_name", "city", "code"]
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
    list_filter = ["status", "school"]
    list_select_related = ["school"]
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
    list_select_related = ["professor", "professor__school"]
    raw_id_fields = ["professor", "author"]
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
    raw_id_fields = ["review", "user"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["review", "user", "created_at"]
    raw_id_fields = ["review", "user"]


@admin.register(AccountProfile)
class AccountProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "email_verified", "email_verified_at"]
    list_filter = ["email_verified"]
    search_fields = ["user__email"]
    raw_id_fields = ["user"]
