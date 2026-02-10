from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
import uuid
from django.utils import timezone
from django.db.models import Count

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

class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    link = models.URLField()
    tier_required = models.CharField(max_length=20, choices=[('FREE', 'Free'), ('PRO', 'Pro'), ('PRO_PLUS', 'Pro Plus')], default='FREE')
    has_certificate = models.BooleanField(default=False)
    max_enrollments = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

class ProgressStep(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField()
    order = models.PositiveIntegerField()  # For sequencing steps
    is_webinar = models.BooleanField(default=False)  # For live webinars if added later

class Certificate(models.Model):
    enrollment = models.OneToOneField('Enrollment', on_delete=models.CASCADE)  # Fixed: Use string reference
    issued_at = models.DateTimeField(auto_now_add=True)
    certificate_file = models.FileField(upload_to='certificates/', null=True, blank=True)

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
    is_proplus = models.BooleanField(default=False)
    mock_interviews_this_month = models.PositiveIntegerField(default=0)  # Track used mock interviews this month
    enrolled_courses = models.ManyToManyField(Course, through='Enrollment', related_name='enrolled_users')
    certificates_earned = models.ManyToManyField(Certificate, related_name='earned_by')

    def mock_interview_limit(self):
        if self.is_proplus:
            return 4
        return 0

    def mock_interviews_remaining(self):
        limit = self.mock_interview_limit()
        return max(0, limit - self.mock_interviews_this_month)

    def can_schedule_mock_interview(self):
        return self.mock_interviews_remaining() > 0

    def increment_mock_interviews(self):
        self.mock_interviews_this_month += 1
        self.save()

    def decrement_mock_interviews(self):
        if self.mock_interviews_this_month > 0:
            self.mock_interviews_this_month -= 1
            self.save()

    def application_limit(self):
        if self.is_proplus:
            return None
        if self.is_pro:
            return 100
        return 20

    def applications_this_month(self):
        now = timezone.now()
        return JobApplication.objects.filter(
            user=self.user,
            applied_at__year=now.year,
            applied_at__month=now.month
        ).count()

    def can_apply(self):
        limit = self.application_limit()
        if limit is None:
            return True
        return self.applications_this_month() < limit

    def __str__(self):
        return self.user.username

class Enrollment(models.Model):
    STAGE_CHOICES = [
        ('ENROLLED', 'Enrolled'),
        ('STARTED', 'Started Course'),
        ('EXAMS', 'Exams'),
        ('INTERVIEW', 'Interview'),
        ('CERTIFIED', 'Certified'),
    ]
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=[('ENROLLED', 'Enrolled'), ('COMPLETED', 'Completed')], default='ENROLLED')
    current_stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default='ENROLLED')  # New field

    class Meta:
        unique_together = ('profile', 'course')

class UserProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE)
    step = models.ForeignKey(ProgressStep, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[('NOT_STARTED', 'Not Started'), ('IN_PROGRESS', 'In Progress'), ('COMPLETED', 'Completed')], default='NOT_STARTED')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('enrollment', 'step')

class InterviewSlot(models.Model):
    date = models.DateField(unique=True)
    max_slots = models.PositiveIntegerField(default=5)
    used_slots = models.PositiveIntegerField(default=0)

    def available_slots(self):
        return max(0, self.max_slots - self.used_slots)

    def can_schedule(self):
        return self.available_slots() > 0

    def increment_slots(self):
        if self.can_schedule():
            self.used_slots += 1
            self.save()

    def decrement_slots(self):
        if self.used_slots > 0:
            self.used_slots -= 1
            self.save()

class Subscription(models.Model):
    PLAN_CHOICES = (
        ("Pro", "Pro"),
        ("Pro Plus", "Pro Plus"),
    )

    BILLING_CYCLE_CHOICES = (
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan_name = models.CharField(max_length=50, choices=PLAN_CHOICES, default="Pro")
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES, default="monthly")
    start_date = models.DateField(auto_now_add=True)
    end_date = models.DateField()
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan_name}"

    @property
    def price_display(self):
        if self.plan_name == "Pro":
            if self.billing_cycle == "monthly":
                return "₹999/month"
            else:
                return "₹8,999/year"
        elif self.plan_name == "Pro Plus":
            return "₹29,999/year"
        return "N/A"

    @property
    def price_amount(self):
        if self.plan_name == "Pro":
            return Decimal("999.00") if self.billing_cycle == "monthly" else Decimal("8999.00")
        elif self.plan_name == "Pro Plus":
            return Decimal("29999.00")
        return Decimal("0.00")

class Invoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    paid = models.BooleanField(default=False)
    file = models.FileField(upload_to="invoices/", null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f"INV-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.invoice_number

class Appointment(models.Model):
    TYPE_CHOICES = [
        ('INTERVIEW', 'Interview'),
        ('ONE_ON_ONE', '1-1 Session'),
    ]

    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('DONE', 'Done'),
        ('POSTPONED', 'Postponed'),
    ]

    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, null=True, blank=True)
    consultant = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultant_appointments"
    )
    appointment_type = models.CharField(max_length=20,
                                        choices=TYPE_CHOICES,
                                        default='INTERVIEW')
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    interview_type = models.CharField(
        max_length=20,
        choices=[('BEHAVIORAL', 'Behavioral'), ('TECHNICAL', 'Technical'), ('CASE_STUDY', 'Case Study')],
        blank=True,
        null=True
    )
    target_role = models.CharField(max_length=100, blank=True)
    video_link = models.URLField(blank=True)
    is_mock_interview = models.BooleanField(default=False)
    waitlist = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.application.user} - {self.appointment_type}"

class MockInterviewFeedback(models.Model):
    appointment = models.OneToOneField(Appointment, on_delete=models.CASCADE, related_name='feedback')
    feedback_report = models.FileField(upload_to='feedback_reports/', blank=True, null=True)  # Uploaded PDF/report
    improvement_plan = models.TextField(blank=True)  # Text-based plan
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)  # Consultant who uploads

    def __str__(self):
        return f"Feedback for {self.appointment}"

class CalendarEvent(models.Model):
    title = models.CharField(max_length=255)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    related_appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    def __str__(self):
        return self.title

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