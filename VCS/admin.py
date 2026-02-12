from django.contrib import admin
from .models import (
    Job, JobApplication, Course, ProgressStep, Certificate,
    Profile, Enrollment, UserProgress, InterviewSlot,
    Subscription, Invoice, Appointment, MockInterviewFeedback,
    CalendarEvent, Interaction, SupportQuery, Notification,
    ChatQuestionAnswer, CandidateChat, ChatEscalation,
    Badge, UserBadge, AnnualReview, SavedJob
)

# Custom admin for Job
@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('job_title', 'company_name', 'location', 'experience', 'salary_range', 'is_exclusive', 'posted_at')
    search_fields = ('job_title', 'company_name', 'location')
    list_filter = ('experience', 'is_exclusive', 'posted_at')
    ordering = ('-posted_at',)

# Custom admin for JobApplication
@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'job', 'status', 'applied_at', 'updated_at')
    search_fields = ('user__username', 'job__job_title', 'status')
    list_filter = ('status', 'applied_at')
    readonly_fields = ('applied_at', 'updated_at')

# Custom admin for Profile
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'tier', 'is_pro', 'is_proplus', 'location', 'phone')
    search_fields = ('user__username', 'skills', 'location')
    list_filter = ('is_pro', 'is_proplus', 'tier')
    readonly_fields = ('applications_this_month', 'chatbot_queries_this_month', 'resume_optimizations_this_month', 'consultant_sessions_this_month', 'mock_interviews_this_month', 'courses_enrolled_this_month')

# Custom admin for Appointment
@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('application', 'consultant', 'appointment_type', 'scheduled_at', 'status')
    search_fields = ('application__user__username', 'consultant__username', 'appointment_type')
    list_filter = ('appointment_type', 'status', 'scheduled_at')
    readonly_fields = ('sla_due', 'sla_complied')

# Custom admin for Invoice
@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'user', 'subscription', 'amount', 'paid', 'date')
    search_fields = ('invoice_number', 'user__username', 'subscription__plan_name')
    list_filter = ('paid', 'date')
    readonly_fields = ('invoice_number', 'date')

# Custom admin for SupportQuery
@admin.register(SupportQuery)
class SupportQueryAdmin(admin.ModelAdmin):
    list_display = ('user', 'subject', 'priority', 'resolved', 'created_at')
    search_fields = ('user__username', 'subject', 'message')
    list_filter = ('priority', 'resolved', 'created_at')

# Basic registrations for other models (no custom admin needed for simplicity)
admin.site.register(Course)
admin.site.register(ProgressStep)
admin.site.register(Certificate)
admin.site.register(Enrollment)
admin.site.register(UserProgress)
admin.site.register(InterviewSlot)
admin.site.register(Subscription)
admin.site.register(MockInterviewFeedback)
admin.site.register(CalendarEvent)
admin.site.register(Interaction)
admin.site.register(Notification)
admin.site.register(ChatQuestionAnswer)
admin.site.register(CandidateChat)
admin.site.register(ChatEscalation)
admin.site.register(Badge)
admin.site.register(UserBadge)
admin.site.register(AnnualReview)
admin.site.register(SavedJob)