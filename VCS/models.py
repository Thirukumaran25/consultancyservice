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



class Course(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    link = models.URLField()

    def __str__(self):
        return self.title


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

    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE)
    consultant = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultant_appointments"
    )
    appointment_type = models.CharField(max_length=20,
                                        choices=TYPE_CHOICES,
                                        default='INTERVIEW' )
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.application.user} - {self.appointment_type}"


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