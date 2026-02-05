from django.db import models
from django.contrib.auth.models import User

# Create your models here.


class Job(models.Model):
    EXPERIENCE_CHOICES = [
        ('FRESHER', 'Fresher'),
        ('1-3', '1–3 Years'),
        ('3-5', '3–5 Years'),
        ('5+', '5+ Years'),
    ]

    company_name = models.CharField(max_length=200, db_index=True)
    job_title = models.CharField(max_length=200, db_index=True)
    location = models.CharField(max_length=100, db_index=True)

    experience = models.CharField(
        max_length=10,
        choices=EXPERIENCE_CHOICES,
        db_index=True
    )

    salary_range = models.IntegerField(help_text="Monthly salary", db_index=True)
    is_remote = models.BooleanField(default=False)

    eligibility = models.TextField()
    job_description = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    saved_by = models.ManyToManyField(User, blank=True, related_name='saved_jobs')
    applied_by = models.ManyToManyField(User, through='JobApplication', related_name='applied_jobs')
    class Meta:
        indexes = [
            models.Index(fields=['job_title']),
            models.Index(fields=['location']),
            models.Index(fields=['experience']),
            models.Index(fields=['salary_range']),
        ]
    def __str__(self):
        return f"{self.job_title} - {self.company_name}"



class JobApplication(models.Model):
    STATUS_CHOICES = [
        ('APPLIED', 'Applied'),
        ('VIEWED', 'Viewed by Recruiter'),
        ('WAITING', 'Waiting for Recruiter Action'),
        ('REJECTED', 'Rejected'),
        ('HIRED', 'Hired'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    applied_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='APPLIED')
    updated_at = models.DateTimeField(auto_now=True)
    resume = models.FileField(upload_to='resumes/', blank=True, null=True)

    class Meta:
        unique_together = ('user', 'job')

    def __str__(self):
        return f"{self.user.username} - {self.job.job_title} ({self.status})"



class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    bio = models.TextField()
    education = models.CharField(max_length=200)
    location = models.CharField(max_length=100)
    experience = models.CharField(max_length=100)
    skills = models.TextField()
    resume = models.FileField(upload_to='resumes/', blank=True, null=True)

    is_pro = models.BooleanField(default=False) 

    def __str__(self):
        return self.user.username



class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan_name = models.CharField(max_length=50, default="Pro")
    start_date = models.DateField(auto_now_add=True)
    end_date = models.DateField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.user.username


class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    link = models.URLField()

    def __str__(self):
        return self.title


class Appointment(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    scheduled_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    reminder_sent = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.application.user} - {self.scheduled_at}"

class Interaction(models.Model):
    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    admin = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.application.user} - {self.created_at}"

class SupportQuery(models.Model):
    PRIORITY = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('ESCALATED', 'Escalated'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY, default='LOW')
    resolved = models.BooleanField(default=False)
    reply = models.TextField(blank=True, null=True) 
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.message


class ChatQuestionAnswer(models.Model):
    CATEGORY_CHOICES = [
        ('General', 'General'),
        ('Python', 'Python'),
        ('Java', 'Java'),
        ('SQL', 'SQL'),
        ('HR', 'HR'),
        ('Behavioral', 'Behavioral'),
    ]

    question = models.CharField(max_length=500, unique=True)
    answer = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='General')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.category}] {self.question}"
    

class CandidateChat(models.Model):
    candidate = models.ForeignKey(User, on_delete=models.CASCADE)
    question = models.TextField()
    answer = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate.username}: {self.question[:50]}"