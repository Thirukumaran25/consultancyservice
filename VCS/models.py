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

    # NEW: For priority and exclusive jobs
    is_exclusive = models.BooleanField(default=False)  # Pro/Pro Plus only
    priority_score = models.FloatField(default=0.0)  # For matching
    recruiter_email = models.EmailField(blank=True)  # For intros

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

    resume_optimizations_this_month = models.PositiveIntegerField(default=0)
    chatbot_queries_this_month = models.PositiveIntegerField(default=0)
    consultant_sessions_this_month = models.PositiveIntegerField(default=0)
    mock_interviews_this_month = models.PositiveIntegerField(default=0)
    courses_enrolled_this_month = models.PositiveIntegerField(default=0)

    is_trainee = models.BooleanField(default=False) 
    course = models.CharField(max_length=100, blank=True, null=True) 
    trainee_plan = models.CharField(max_length=10, choices=[('pro', 'Pro'), ('proplus', 'Pro Plus')], default='pro') 

    consultant_hours_used_this_month = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.0
    )

    enrolled_courses = models.ManyToManyField(
        'Course', through='Enrollment', related_name='enrolled_users'
    )

    certificates_earned = models.ManyToManyField(
        'Certificate', related_name='earned_by'
    )

    dedicated_consultant = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dedicated_profiles',
        limit_choices_to={'is_staff': True}
    )

    @property
    def tier(self):
        if self.is_proplus or (self.is_trainee and self.trainee_plan == 'proplus'):
            return "PROPLUS"
        elif self.is_pro or (self.is_trainee and self.trainee_plan == 'pro'):
            return "PRO"
        return "FREE"

    def get_limits(self):
        """
        Returns all limits based on subscription tier or trainee plan.
        None = Unlimited
        """
        limits = {
            "FREE": {
                "applications": 20,
                "chatbot": 0,
                "resume": 0,
                "consultant_sessions": 0,
                "mock_interviews": 0,
                "courses": 0,
            },
            "PRO": {
                "applications": 100,
                "chatbot": 250,
                "resume": 3,
                "consultant_sessions": 1,
                "mock_interviews": 0,
                "courses": 0,
            },
            "PROPLUS": {
                "applications": None,   
                "chatbot": None,      
                "resume": 20,
                "consultant_sessions": 4,
                "mock_interviews": 4,
                "courses": 1,
            }
        }

        # UPDATED: Check for trainee first
        if self.is_trainee:
            if self.trainee_plan == 'proplus':
                return limits["PROPLUS"]
            else:
                return limits["PRO"]
        
        return limits[self.tier]

    def applications_this_month(self):
        now = timezone.now()
        return self.user.jobapplication_set.filter(
            applied_at__year=now.year,
            applied_at__month=now.month
        ).count()

    def can_apply(self):
        limit = self.get_limits()["applications"]
        if limit is None:
            return True
        return self.applications_this_month() < limit

    def check_quota(self, feature_name, used_value):
        """
        Generic quota checker.
        feature_name must match keys in get_limits().
        """
        limit = self.get_limits()[feature_name]

        if limit is None:
            return True 

        return used_value < limit

    def can_use_chatbot(self):
        # UPDATED: For trainees, use trainee_plan logic
        if self.is_trainee:
            if self.trainee_plan == 'proplus':
                return True
            return self.chatbot_queries_this_month < 250
        return self.check_quota("chatbot", self.chatbot_queries_this_month)

    def can_optimize_resume(self):
        return self.check_quota("resume", self.resume_optimizations_this_month)

    def can_schedule_session(self):
        return self.check_quota("consultant_sessions", self.consultant_sessions_this_month)

    def can_schedule_mock_interview(self):
        return self.check_quota("mock_interviews", self.mock_interviews_this_month)

    def can_enroll_course(self):
        return self.check_quota("courses", self.courses_enrolled_this_month)

    def increment_chatbot_queries(self):
        """Increment the chatbot queries counter."""
        self.chatbot_queries_this_month += 1
        self.save()

    def increment_usage(self, field_name):
        """
        Generic increment method.
        Example: self.increment_usage("chatbot_queries_this_month")
        """
        setattr(self, field_name, getattr(self, field_name) + 1)
        self.save(update_fields=[field_name])

    def award_badges(self):
        badges = Badge.objects.all()
        for badge in badges:
            if eval(badge.criteria):
                UserBadge.objects.get_or_create(user=self.user, badge=badge)

    @staticmethod
    def proplus_subscriber_count():
        return Profile.objects.filter(is_proplus=True).count()

    @staticmethod
    def proplus_limit():
        return 50

    @staticmethod
    def can_upgrade_to_proplus():
        return Profile.proplus_subscriber_count() < Profile.proplus_limit()

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
    current_stage = models.IntegerField(default=1) 
    status = models.CharField(max_length=20, choices= STAGE_CHOICES, default='ENROLLED')

    def get_stage_number(self):
        status_to_number = {
            'ENROLLED': 1,
            'STARTED': 2,
            'EXAMS': 3,
            'INTERVIEW': 4,
            'CERTIFIED': 5,
        }
        return status_to_number.get(self.status, 1) 

    def save(self, *args, **kwargs):
        if self.status == 'ENROLLED':
            self.current_stage = 1
        elif self.status == 'STARTED':
            self.current_stage = 2
        elif self.status == 'EXAMS':
            self.current_stage = 3
        elif self.status == 'INTERVIEW':
            self.current_stage = 4
        elif self.status == 'COMPLETED':
            self.current_stage = 5 
        super().save(*args, **kwargs)

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

    # NEW: SLA tracking
    sla_due = models.DateTimeField(null=True, blank=True)
    sla_complied = models.BooleanField(default=False)

    def set_sla(self):
        if self.appointment_type == 'ONE_ON_ONE':
            hours = 2 if self.application.user.profile.is_proplus else 4
            self.sla_due = self.scheduled_at + timezone.timedelta(hours=hours)
            self.save()

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


class ChatEscalation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.TextField()
    escalated_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    sla_due = models.DateTimeField()  
    priority = models.CharField(max_length=10, default='HIGH')  

class Badge(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    criteria = models.JSONField()
    icon = models.ImageField(upload_to='badges/', blank=True) 

class UserBadge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)

class AnnualReview(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    report = models.TextField()
    roadmap = models.TextField()
    completed_at = models.DateTimeField(null=True, blank=True)

class SavedJob(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    job = models.ForeignKey(Job, on_delete=models.CASCADE)
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'job')

    def __str__(self):
        return f"{self.user.username} saved {self.job.job_title}"
    

class Referral(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='referrals_made')
    referred = models.OneToOneField(User, on_delete=models.CASCADE, related_name='referred_by')
    created_at = models.DateTimeField(auto_now_add=True)
    reward_given = models.BooleanField(default=False)