from django import forms
from django.contrib.auth.models import User
from .models import Profile,JobApplication,Job
from django.forms import ModelForm
from django.core.exceptions import ValidationError


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
