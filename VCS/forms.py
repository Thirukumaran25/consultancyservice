from django import forms
from django.contrib.auth.models import User
from .models import Profile,JobApplication,Job,Appointment
from django.forms import ModelForm
from django.core.exceptions import ValidationError
import re


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
        ]


# class AppointmentForm(forms.ModelForm):
#     application = forms.ModelChoiceField(
#         queryset=JobApplication.objects.select_related('user', 'job'),
#         empty_label="Select a Candidate",
#         widget=forms.Select(attrs={'class': 'border rounded p-2 w-full'}),
#         label="Candidate"
#     )
    
#     class Meta:
#         model = Appointment
#         fields = ['application', 'scheduled_at', 'notes']
#         widgets = {
#             'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
#             'notes': forms.Textarea(attrs={'rows': 4}),
#         }
    
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.fields['application'].label_from_instance = lambda obj: obj.user.username


# class PostponeAppointmentForm(forms.ModelForm):
#     class Meta:
#         model = Appointment
#         fields = ['scheduled_at', 'notes']
#         widgets = {
#             'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
#             'notes': forms.Textarea(attrs={'rows': 4}),
#         }
    
#     def save(self, commit=True):
#         instance = super().save(commit=False)
#         instance.status = 'POSTPONED'
#         if commit:
#             instance.save()
#         return instance


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

class PostponeAppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['scheduled_at', 'notes']
        widgets = {
            'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'required': True}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }
    
    # Override save to set status to POSTPONED
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = 'POSTPONED'
        if commit:
            instance.save()
        return instance