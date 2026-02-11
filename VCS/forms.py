from django import forms
from django.contrib.auth.models import User
from .models import (Profile,JobApplication,Job,Appointment,
                     InterviewSlot,MockInterviewFeedback,UserProgress,
                     Enrollment,Course, ChatEscalation, Badge, AnnualReview)  # UPDATED: Added new models
from django.forms import ModelForm
from django.core.exceptions import ValidationError
import re
from django.utils import timezone

class SignupForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full mt-1 px-3 py-2 border rounded focus:outline-none focus:ring'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'w-full mt-1 px-3 py-2 border rounded'}),
            'email': forms.EmailInput(attrs={'class': 'w-full mt-1 px-3 py-2 border rounded'}),
        }
    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise ValidationError("Username already exists. Please login.")

        if username.isdigit():
            raise ValidationError("Username cannot contain only numbers. Use letters also.")

        if not re.match("^[A-Za-z_]+$", username):
            raise ValidationError("Username can only contain letters and underscore.")

        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email already registered.")
        return email

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'phone','bio','education','location','experience','skills','resume',
        ]
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'w-full border rounded p-2'}),
            'bio': forms.Textarea(attrs={'class': 'w-full border rounded p-2'}),
            'education': forms.TextInput(attrs={'class': 'w-full border rounded p-2'}),
            'location': forms.TextInput(attrs={'class': 'w-full border rounded p-2'}),
            'experience': forms.TextInput(attrs={'class': 'w-full border rounded p-2'}),
            'skills': forms.Textarea(attrs={'class': 'w-full border rounded p-2'}),
        }

def validate_file_size(value):
    limit = 5 * 1024 * 1024 
    if value.size > limit:
        raise ValidationError('File too large. Size should not exceed 5 MB.')

class JobApplicationForm(forms.Form):
    full_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500'
        })
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-3 py-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500'
        })
    )
    resume = forms.FileField(
        required=True,
        validators=[validate_file_size],
        widget=forms.ClearableFileInput(attrs={'class': 'w-full'})
    )

class JobApplicationStatusForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-control'})
        }

class JobForm(ModelForm):
    class Meta:
        model = Job
        fields = [
            'job_title',
            'company_name',
            'location',
            'experience',
            'salary_range',
            'is_remote',
            'eligibility',
            'job_description',
            'is_exclusive',  # NEW: Added for exclusive jobs
            'recruiter_email',  # NEW: Added for intros
        ]

class AppointmentForm(forms.ModelForm):
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(profile__isnull=False),  # Only users with profiles
        empty_label="Select a Candidate",
        widget=forms.Select(attrs={'class': 'border rounded p-2 w-full'}),
        label="Candidate"
    )
    
    class Meta:
        model = Appointment
        fields = ['user', 'scheduled_at', 'notes']  # Changed 'application' to 'user'
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }
    def clean_scheduled_at(self):
        scheduled_at = self.cleaned_data.get('scheduled_at')
        if scheduled_at:
            if scheduled_at <= timezone.now():
                raise ValidationError("Scheduled time must be in the future.")
            # Check admin slots
            slot, created = InterviewSlot.objects.get_or_create(date=scheduled_at.date())
            if not slot.can_schedule():
                raise ValidationError("No available slots for this date.")
        return scheduled_at

class PostponeAppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['scheduled_at', 'notes']
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = 'POSTPONED'
        if commit:
            instance.save()
        return instance

class MockInterviewForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['scheduled_at', 'interview_type', 'target_role', 'notes']
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
            'interview_type': forms.Select(attrs={'class': 'border rounded p-2 w-full'}),
            'target_role': forms.TextInput(attrs={'class': 'border rounded p-2 w-full', 'placeholder': 'e.g., Software Engineer'}),
            'notes': forms.Textarea(attrs={'rows': 4, 'class': 'border rounded p-2 w-full'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        profile = self.user.profile
        if not profile.can_schedule_mock_interview():
            raise ValidationError("You have exhausted your monthly mock interview quota. Wait for next month or upgrade.")
        return cleaned_data

class MockInterviewFeedbackForm(forms.ModelForm):
    class Meta:
        model = MockInterviewFeedback
        fields = ['feedback_report', 'improvement_plan']

class EnrollmentForm(forms.Form):
    course_id = forms.IntegerField(widget=forms.HiddenInput())

    def clean(self):
        cleaned_data = super().clean()
        course_id = cleaned_data.get('course_id')
        course = Course.objects.get(id=course_id)
        profile = self.user.profile  # Assumes user is passed to form

        # Tier verification
        if course.tier_required == 'PRO_PLUS' and not profile.is_proplus:
            raise ValidationError("This course requires Pro Plus subscription.")
        if course.tier_required == 'PRO' and not (profile.is_pro or profile.is_proplus):
            raise ValidationError("This course requires Pro subscription.")

        # Quota enforcement
        if course.max_enrollments > 0 and Enrollment.objects.filter(user=self.user, course=course).count() >= course.max_enrollments:
            raise ValidationError("Enrollment limit reached for this course.")

        return cleaned_data

class ProgressUpdateForm(forms.ModelForm):
    class Meta:
        model = UserProgress
        fields = ['status']

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['title', 'description', 'link', 'tier_required', 'has_certificate', 'max_enrollments']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'link': forms.URLInput(attrs={'placeholder': 'https://example.com'}),
        }

# NEW: Forms for new models
class ChatEscalationForm(forms.ModelForm):
    class Meta:
        model = ChatEscalation
        fields = ['query']

class BadgeForm(forms.ModelForm):
    class Meta:
        model = Badge
        fields = ['name', 'description', 'criteria']

class AnnualReviewForm(forms.ModelForm):
    class Meta:
        model = AnnualReview
        fields = ['report', 'roadmap']