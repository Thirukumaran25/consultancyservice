from django.contrib import admin
from .models import ChatQuestionAnswer, CandidateChat,Job

# Register your models here.

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = (
        'job_title',
        'company_name',
        'location',
        'experience',
        'salary_range',
        'posted_at'
    )
    search_fields = ('job_title', 'company_name', 'location')
    list_filter = ('location',)



@admin.register(ChatQuestionAnswer)
class ChatQuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'answer', 'category', 'created_at')
    list_filter = ('category',)
    search_fields = ('question',)

@admin.register(CandidateChat)
class CandidateChatAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'question', 'answer', 'created_at')
    search_fields = ('candidate__username', 'question')