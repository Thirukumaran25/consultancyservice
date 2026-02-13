from django.shortcuts import render,redirect,get_object_or_404
from django.contrib.auth import authenticate, login
from .forms import (SignupForm,ProfileForm,JobApplicationForm,
                    JobForm,AppointmentForm,PostponeAppointmentForm,
                    MockInterviewForm,MockInterviewFeedbackForm,
                    CourseForm, ChatEscalationForm, BadgeForm, AnnualReviewForm)  # UPDATED: Added new forms
from .models import (ChatQuestionAnswer,Invoice, CandidateChat,
                     Job,Profile,Subscription,Course,
                     JobApplication,Appointment,Interaction,
                     SupportQuery,Notification,CalendarEvent,
                     MockInterviewFeedback,InterviewSlot,
                     Enrollment,Certificate,UserProgress,
                     ChatEscalation, Badge, UserBadge, AnnualReview,
                     Referral,)

from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from difflib import SequenceMatcher
from datetime import date, timedelta
import datetime
from django.core.paginator import Paginator
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import re
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from .gemini import ask_gemini
from django.utils import timezone
from django.utils.timezone import now
import razorpay
from django.conf import settings
import uuid
from django.template.loader import render_to_string
from django.urls import reverse
from django.contrib.auth.models import User 
from django.core.mail import send_mail 
from django.utils import timezone
from celery import shared_task 
from decimal import Decimal
from .decorators import rate_limit
import logging
import base64  
from io import BytesIO 
from reportlab.lib.pagesizes import letter  # Added for PDF page size
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # Added for PDF styling
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer  # Added for PDF content
logger = logging.getLogger(__name__)




def recruiter_required(view_func):
    return user_passes_test(
        lambda u: u.is_authenticated and (u.is_staff or u.is_superuser or u.groups.filter(name='Recruiter').exists())
    )(view_func)

def highlight_keywords(text, keywords):
    for kw in keywords:
        text = re.sub(f"(?i)({re.escape(kw)})", r"<b>\1</b>", text)
    return text

# Create your views here.

FREE_CHAT_LIMIT = 10
PRO_CHAT_LIMIT = 250  


def ratelimit_error(request, exception):
    return JsonResponse({'error': 'Rate limit exceeded. Try again later.'}, status=429)

@rate_limit('5/m')
@csrf_exempt
@login_required
def chatbot_api(request):
    if request.method != 'POST':
        return JsonResponse({'reply': "Invalid request."}, status=400)
    
    try:
        data = json.loads(request.body)
        user_question = data.get("message", "").strip()
    except json.JSONDecodeError:
        return JsonResponse({"reply": "Invalid JSON data"}, status=400)
    
    if not user_question:
        return JsonResponse({'reply': "Please enter a question."}, status=400)
    
    try:
        profile, _ = Profile.objects.get_or_create(user=request.user)
        if not profile.can_use_chatbot():
            return JsonResponse({
                'reply': "⚠️ You have reached your limit. Upgrade.",
                'upgrade_required': True
            })
        
        job_keywords = ["job", "jobs", "vacancy", "opening", "developer", "engineer"]
        if any(word in user_question for word in job_keywords):
            clean_words = [w for w in user_question.split() if w not in job_keywords]

            query = Q()
            for word in clean_words:
                query |= Q(job_title__icontains=word) | Q(job_description__icontains=word)

            jobs = Job.objects.filter(query).distinct()[:5]

            if jobs.exists():
                job_list = []
                for job in jobs:
                    job_list.append({
                        "id": job.id,
                        "title": job.job_title,
                        "company": job.company_name
                    })

                answer = {
                    "type": "job_list",
                    "jobs": job_list
                }
                source = "db"
            else:
                answer = {
                    "type": "text",
                    "message": "❌ No jobs available for your query right now."
                }
                source = "db"
            
            CandidateChat.objects.create(
                candidate=request.user,
                question=user_question,
                answer=json.dumps(answer)
            )
            profile.increment_chatbot_queries()
            return JsonResponse({
                'reply': answer,
                'source': source
            })
        else:
            # UPDATED: Add escalation for Pro Plus
            if profile.is_proplus and "complex" in user_question.lower():
                escalation = ChatEscalation.objects.create(
                    user=request.user,
                    query=user_question,
                    sla_due=timezone.now() + timedelta(hours=2)
                )
                return JsonResponse({'reply': "Escalated to consultant. Response in 2 hours."})
            
            try:
                faq = ChatQuestionAnswer.objects.get(question__iexact=user_question)
                answer = faq.answer
                source = "db"
            except ChatQuestionAnswer.DoesNotExist:
                try:
                    answer = ask_gemini(user_question)
                    source = "gemini"
                except Exception as e:
                    logger.error(f"Gemini API failed for user {request.user.username}: {str(e)}")
                    answer = "Sorry, the AI service is temporarily unavailable. Please try again later."
                    source = "error"
            
            CandidateChat.objects.create(
                candidate=request.user,
                question=user_question,
                answer=json.dumps(answer) if isinstance(answer, dict) else answer
            )
            profile.increment_chatbot_queries()
            return JsonResponse({
                'reply': answer,
                'source': source
            })
    except Exception as e:
        logger.error(f"Chatbot API error for user {request.user.username}: {str(e)}")
        return JsonResponse({'reply': 'An error occurred. Please try again later.'}, status=500)

@login_required
def candidate_chat(request):
    chats = CandidateChat.objects.filter(candidate=request.user).order_by('created_at')
    
    coding_suggestions = ChatQuestionAnswer.objects.filter(category__in=['Python','Java','SQL'])[:5]
    hr_suggestions = ChatQuestionAnswer.objects.filter(category='HR')[:5]
    behavioral_suggestions = ChatQuestionAnswer.objects.filter(category='Behavioral')[:5]

    return render(request, 'jobs/candidate_chat.html', {
        'chats': chats,
        'coding_suggestions': coding_suggestions,
        'hr_suggestions': hr_suggestions,
        'behavioral_suggestions': behavioral_suggestions
    })

@login_required
def send_message(request):
    if request.method == 'POST':
        user_question = request.POST.get('question', '').strip()
        
        profile = Profile.objects.get(user=request.user)
        if not profile.can_use_chatbot():
            return JsonResponse({
                'error': "Limit reached. Upgrade.",
                'upgrade_required': True
            })
        
        if user_question:
            try:
                answer_obj = ChatQuestionAnswer.objects.get(question__iexact=user_question)
                answer = answer_obj.answer
            except ChatQuestionAnswer.DoesNotExist:
                keywords = user_question.split()
                query = Q()
                for kw in keywords:
                    query |= Q(question__icontains=kw)

                similar_qs = ChatQuestionAnswer.objects.filter(query)[:3]

                if similar_qs.exists():
                    answer = "I found answers to similar questions:\n\n"
                    for q in similar_qs:
                        ans_text = highlight_keywords(q.answer, keywords)
                        answer += f"Q: {q.question} \nA: {ans_text}\n\n"
                else:
                    answer = "Sorry, I don't have an answer for that."

            chat = CandidateChat.objects.create(
                candidate=request.user,
                question=user_question,
                answer=answer
            )
            profile.increment_chatbot_queries()  # UPDATED: Increment quota
            return JsonResponse({
                'question': chat.question,
                'answer': chat.answer,
                'created_at': chat.created_at.strftime("%Y-%m-%d %H:%M")
            })

    return JsonResponse({'error': 'Invalid request'})

@login_required
def chat_history(request):
    chats = CandidateChat.objects.filter(candidate=request.user).order_by('created_at')
    data = [{'question': c.question, 'answer': c.answer} for c in chats]
    return JsonResponse({'chats': data})

@login_required
@require_POST
def clear_chat(request):
    CandidateChat.objects.filter(candidate=request.user).delete()
    return JsonResponse({'success': True})

@staff_member_required
def chatfaq_list(request):
    search = request.GET.get('search', '')
    if search:
        faqs = ChatQuestionAnswer.objects.filter(question__icontains=search)
    else:
        faqs = ChatQuestionAnswer.objects.all().order_by('-id')

    return render(request, 'admin/chatfaq_modal.html', {'faqs': faqs, 'search': search})

@staff_member_required
def chatfaq_save(request):
    if request.method == "POST":
        faq_id = request.POST.get('id')
        question = request.POST.get('question')
        answer = request.POST.get('answer')
        category = request.POST.get('category')

        if faq_id:  # Edit
            faq = get_object_or_404(ChatQuestionAnswer, id=faq_id)
            faq.question = question
            faq.answer = answer
            faq.category = category
            faq.save()
        else:  # Add
            ChatQuestionAnswer.objects.create(
                question=question,
                answer=answer,
                category=category
            )

        return JsonResponse({'success': True})

@staff_member_required
def chatfaq_delete(request, id):
    if request.method == 'POST':
        faq = get_object_or_404(ChatQuestionAnswer, id=id)
        faq.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

def home(request):
    return render(request, 'home.html', {})

@rate_limit('10/h')
def user_login(request):
    next_url = request.GET.get("next") or request.POST.get("next")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user:
            login(request, user)

            if next_url:
                return redirect(next_url)

            return redirect(
                'admin_dashboard' if user.is_staff else 'home'
            )

        return render(
            request,
            "registration/login.html",
            {
                "error": "Invalid username or password.",
                "next": next_url
            }
        )

    return render(request, "registration/login.html", {"next": next_url})


def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()  # Save the user first
            
            # Handle referral after user is saved
            referral_code = request.GET.get('ref')  # e.g., /signup/?ref=username
            if referral_code:
                try:
                    referrer = User.objects.get(username=referral_code)
                    Referral.objects.create(referrer=referrer, referred=user)
                except User.DoesNotExist:
                    pass
            
            # Get or create profile (ensures it exists even if signal fails)
            profile, created = Profile.objects.get_or_create(user=user)
            profile.award_badges()
            
            # Authenticate and login
            user = authenticate(username=user.username, password=form.cleaned_data['password'])
            if user is not None:
                login(request, user)
                
                # Send welcome email
                send_mail(
                    subject="Welcome to VCS Career Services!",
                    message=f"Hi {user.username},\n\nWelcome to VCS! Your account has been created successfully. Start exploring jobs and building your career.\n\nBest,\nVCS Team",
                    from_email="noreply@yourapp.com",
                    recipient_list=[user.email],
                    fail_silently=True,
                )
                
                return redirect('/')
    else:
        form = SignupForm()
    return render(request, 'signup.html', {'form': form})

def job_list(request):
    jobs = Job.objects.all().order_by('-posted_at')

    title = request.GET.get('title')
    location = request.GET.get('location')
    experience = request.GET.get('experience')
    min_salary = request.GET.get('min_salary')
    remote = request.GET.get('remote')
    saved = request.GET.get('saved')
    applied = request.GET.get('applied')
    skills = request.GET.get('skills')

    if title:
        jobs = jobs.filter(job_title__icontains=title)

    if location:
        jobs = jobs.filter(location=location)

    if experience:
        jobs = jobs.filter(experience=experience)

    if min_salary:
        jobs = jobs.filter(salary_range__gte=min_salary)

    if remote == "1":
        jobs = jobs.filter(is_remote=True)

    if request.user.is_authenticated:
        profile = request.user.profile
        # UPDATED: Hide exclusive jobs for Free users
        if not (profile.is_pro or profile.is_proplus):
            jobs = jobs.filter(is_exclusive=False)

        if profile.is_pro or profile.is_proplus:
            for job in jobs:
                score = SequenceMatcher(
                    None,
                    profile.skills.lower(),
                    job.job_description.lower()
                ).ratio() * 100
                job.match_score = round(score, 1)

        if saved == "1":
            jobs = jobs.filter(saved_by=request.user)

        if applied == "1":
            jobs = jobs.filter(jobapplication__user=request.user)

    if skills:
        for skill in skills.split(','):
            jobs = jobs.filter(job_description__icontains=skill.strip())

    locations = Job.objects.values_list('location', flat=True).distinct()

    paginator = Paginator(jobs, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'jobs': page_obj,
        'locations': locations,
        'page_obj': page_obj,
        'filters': request.GET
    }

    return render(request, 'jobs.html', context)

def search(request):
    query = request.GET.get('q', '')
    results = []
    if query:
        results = Job.objects.filter(
            Q(job_title__icontains=query) |
            Q(company_name__icontains=query) |
            Q(location__icontains=query)
        )

    return render(request, 'search_results.html', {
        'query': query,
        'results': results
    })

def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    has_applied = False

    applications_used = 0
    applications_limit = None
    limit_reached = False
    show_warning = False

    if request.user.is_authenticated:
        has_applied = JobApplication.objects.filter(
            job=job,
            user=request.user
        ).exists()

        profile = request.user.profile

        applications_used = profile.applications_this_month()

        # 🔥 NEW SYSTEM
        limits = profile.get_limits()
        applications_limit = limits["applications"]

        if applications_limit is not None:
            limit_reached = applications_used >= applications_limit
            show_warning = applications_used >= (applications_limit - 2)

    return render(request, 'job_detail.html', {
        'job': job,
        'has_applied': has_applied,
        'applications_used': applications_used,
        'applications_limit': applications_limit,
        'limit_reached': limit_reached,
        'show_warning': show_warning,
    })


@login_required
def save_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    if request.method == "POST":
        if request.user in job.saved_by.all():
            job.saved_by.remove(request.user)
        else:
            job.saved_by.add(request.user)    
    return redirect('job_detail', pk=pk)


@login_required
def apply_job(request, pk):
    job = get_object_or_404(Job, pk=pk)
    profile = get_object_or_404(Profile, user=request.user)

    if not profile.can_apply():
        messages.error(
            request,
            "You’ve reached your monthly application limit. Upgrade to apply for more jobs."
        )
        return redirect('upgrade_plan') 

    if job.is_exclusive and not (profile.is_pro or profile.is_proplus):
        messages.error(request, "Exclusive job. Upgrade to Pro.")
        return redirect('job_detail', pk=pk)

    application, created = JobApplication.objects.get_or_create(
        user=request.user,
        job=job,
        defaults={'resume': profile.resume}
    )

    if request.method == 'POST':
        form = JobApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            if form.cleaned_data.get('resume'):
                profile.resume = form.cleaned_data['resume']
                profile.save()
                application.resume = profile.resume
                application.save()

            messages.success(request, "Job application submitted successfully!")
            if profile.is_proplus and job.recruiter_email:
                subject = f"Introduction: {request.user.username} for {job.job_title} at {job.company_name}"
                message = f"""
                Dear Recruiter,

                We are pleased to introduce {request.user.username} as a strong candidate for the {job.job_title} position at {job.company_name}.

                Candidate Details:
                - Name: {request.user.username}
                - Email: {request.user.email}
                - Skills: {profile.skills}
                - Experience: {profile.experience}
                - Resume: Attached or available in the application.

                As a Pro Plus user, {request.user.username} has access to premium features, including priority matching and dedicated support.

                Please review their application and consider them for an interview.

                Best regards,
                VCS Career Services Team
                """
                send_mail(
                    subject=subject,
                    message=message,
                    from_email='noreply@yourapp.com',
                    recipient_list=[job.recruiter_email],
                    fail_silently=True,
                )
                messages.info(request, "A recruiter introduction email has been sent on your behalf.")

            return redirect('applied_jobs')
    else:
        form = JobApplicationForm()

    return render(request, 'apply_job.html', {
        'job': job,
        'form': form,
    })

@login_required
def profile(request):
    profile, created = Profile.objects.get_or_create(user=request.user)

    fields = [profile.phone, profile.bio, profile.education, profile.location,
              profile.experience, profile.skills, profile.resume]
    filled = sum(1 for f in fields if f)
    completion = int((filled / len(fields)) * 100) 
    
    mock_feedbacks = MockInterviewFeedback.objects.filter(appointment__application__user=request.user)
    subscription = getattr(request.user, "subscription", None)
    enrollments = Enrollment.objects.filter(profile=request.user.profile).select_related('course')[:5]
    certificates = Certificate.objects.filter(enrollment__profile=request.user.profile)
    
    badges = UserBadge.objects.filter(user=request.user)
    
    quota_data = {}
    
    # Applications (all tiers)
    if profile.application_limit and profile.application_limit > 0:
        quota_data['applications_percent'] = min((profile.applications_this_month / profile.application_limit) * 100, 100)
    else:
        quota_data['applications_percent'] = 100
    
    # Chatbot (Pro/Pro Plus)
    if profile.is_pro or profile.is_proplus:
        if profile.chatbot_limit and profile.chatbot_limit > 0:
            quota_data['chatbot_percent'] = min((profile.chatbot_queries_this_month / profile.chatbot_limit) * 100, 100)
        else:
            quota_data['chatbot_percent'] = 100 
    
    # Resume Optimizations (Pro/Pro Plus)
    if profile.is_pro or profile.is_proplus:
        quota_data['resume_percent'] = min((profile.resume_optimizations_this_month / profile.resume_optimization_limit) * 100, 100)
    
    # Consultant Sessions (Pro/Pro Plus)
    if profile.is_pro or profile.is_proplus:
        quota_data['consultant_percent'] = min((profile.consultant_sessions_this_month / profile.consultant_session_limit) * 100, 100)
    
    # Mock Interviews (Pro Plus only)
    if profile.is_proplus:
        quota_data['mock_percent'] = min((profile.mock_interviews_this_month / profile.mock_interview_limit) * 100, 100)

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {
        'form': form,
        'profile': profile,
        'completion': completion,
        'subscription': subscription,
        'mock_feedbacks': mock_feedbacks,
        'enrollments': enrollments,
        'certificates': certificates,
        'badges': badges, 
        'quota_data': quota_data,  
    })

@login_required
def upgrade_plan(request):
    profile = Profile.objects.get(user=request.user)

    if request.method == "POST":
        plan = request.POST.get("plan")
        if plan == "pro_monthly":
            plan_name = "Pro"
            billing_cycle = "monthly"
            amount = 99900  
        elif plan == "pro_yearly":
            plan_name = "Pro"
            billing_cycle = "yearly"
            amount = 899900 
        elif plan == "pro_plus":
            if not Profile.can_upgrade_to_proplus():
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': 'Pro Plus limit reached. Added to waitlist.'})
                messages.error(request, "Pro Plus limit reached. Added to waitlist.")
                return redirect('upgrade_plan')
            plan_name = "Pro Plus"
            billing_cycle = "yearly"
            amount = 2999900 
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Invalid plan selected.'})
            return redirect("upgrade_plan")


        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order_data = {
            "amount": amount,
            "currency": "INR",
            "payment_capture": "1"  
        }
        try:
            order = client.order.create(data=order_data)
            order_id = order['id']
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': f'Payment initiation failed: {str(e)}'})
            messages.error(request, f"Payment initiation failed: {str(e)}")
            return redirect('upgrade_plan')


        request.session['plan'] = plan_name
        request.session['cycle'] = billing_cycle
        request.session['amount'] = amount / 100 
        request.session['razorpay_order_id'] = order_id


        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'order_id': order_id,
                'amount': amount,
                'key': settings.RAZORPAY_KEY_ID,
                'plan': plan_name,
                'billing_cycle': billing_cycle,
            })

        return redirect('upgrade_plan')

    return render(request, "upgrade.html")


@login_required
def subscription_dashboard(request):
    default_plan = "Pro"

    subscription, created = Subscription.objects.get_or_create(
        user=request.user,
        defaults={
            "plan_name": default_plan,
            "billing_cycle": "yearly",
            "end_date": date.today() + timedelta(days=365),
            "active": True
        }
    )

    invoices = Invoice.objects.filter(user=request.user).order_by('-date')

    return render(request, "subscription.html", {
        "subscription": subscription,
        "invoices": invoices
    })

@login_required
def saved_jobs(request):
    jobs = request.user.saved_jobs.all()
    return render(request, 'saved_jobs.html', {'jobs': jobs})

@login_required
def applied_jobs(request):
    applications = JobApplication.objects.filter(user=request.user).select_related('job').order_by('-applied_at')
    return render(request, 'applied_jobs.html', {'applications': applications})

@login_required
def job_matching(request):
    profile = request.user.profile
    jobs = Job.objects.all()

    matched_jobs = []

    for job in jobs:
        score = SequenceMatcher(
            None,
            profile.skills.lower(),
            job.job_description.lower()
        ).ratio() * 100

        matched_jobs.append({
            "job": job,
            "score": round(score, 2)
        })

    matched_jobs = sorted(matched_jobs, key=lambda x: x["score"], reverse=True)

    return render(request, "job_matching.html", {
        "matched_jobs": matched_jobs
    })


@login_required
def ai_resume_optimizer(request):
    user = request.user
    profile = get_object_or_404(Profile, user=user)
    
    # Check if user can optimize resume (for Pro/Pro Plus or trainees)
    if not (profile.is_pro or profile.is_proplus or (profile.is_trainee and (profile.trainee_plan == 'pro' or profile.trainee_plan == 'proplus'))):
        messages.error(request, "You need a Pro or Pro Plus plan to use this feature.")
        return redirect('upgrade_plan')
    
    if not profile.can_optimize_resume():
        messages.error(request, f"You've reached your monthly limit of {profile.get_limits()['resume']} resume optimizations.")
        return redirect('profile')
    
    # Initialize context variables
    score = None
    matched_keywords = []
    missing_keywords = []
    suggestions = []
    pdf_base64 = None
    is_pdf = False  # Flag to indicate if it's PDF or text
    
    resume_optimization_limit = profile.get_limits()['resume']
    resume_percent = (profile.resume_optimizations_this_month / resume_optimization_limit) * 100 if resume_optimization_limit else 0
    
    if request.method == 'POST':
        job_title = request.POST.get('job_title')
        resume_text = request.POST.get('resume_text')
        
        if job_title and resume_text:
            try:
                # Craft concise prompt for analysis (fits 10-line limit, forces JSON)
                prompt = f"""
                Analyze the resume for the job: {job_title}.
                Resume text (truncated): {resume_text[:500]}
                
                Return ONLY the JSON object, no other text:
                {{"score": 85, "matched_keywords": ["Python", "Django"], "missing_keywords": ["React", "AWS"], "suggestions": ["Add cloud experience.", "Highlight projects."]}}
                """
                
                # Call your ask_gemini function
                response_text = ask_gemini(prompt)
                
                if response_text == "⚠️ AI service is temporarily unavailable.":
                    raise Exception("AI service unavailable")
                
                # Debug: Print raw response to console
                print("🔍 GEMINI RAW RESPONSE:", repr(response_text))
                
                # Parse JSON response (try direct first)
                data = None
                try:
                    data = json.loads(response_text)
                    print("✅ JSON PARSED DIRECTLY")
                except json.JSONDecodeError:
                    # Try regex to extract JSON
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(0))
                            print("✅ JSON EXTRACTED VIA REGEX")
                        except json.JSONDecodeError as e2:
                            print("❌ REGEX EXTRACTION FAILED:", e2)
                    else:
                        print("❌ NO JSON FOUND IN RESPONSE")
                
                # Always generate downloadable content (PDF or text)
                enhanced_resume_text = f"Enhanced Resume for {job_title}\n\n{resume_text}\n\nSuggestions Applied:\n" + "\n".join(suggestions if data else ["Review and refine based on job requirements."])
                
                if data:
                    score = data.get('score', 0)
                    matched_keywords = data.get('matched_keywords', [])
                    missing_keywords = data.get('missing_keywords', [])
                    suggestions = data.get('suggestions', [])
                    
                    # Try PDF generation
                    try:
                        buffer = BytesIO()
                        doc = SimpleDocTemplate(buffer, pagesize=letter)
                        styles = getSampleStyleSheet()
                        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
                        normal_style = styles['Normal']
                        
                        story = [
                            Paragraph(f"Enhanced Resume for {job_title}", title_style),
                            Spacer(1, 12),
                            Paragraph("Original Resume:", styles['Heading2']),
                            Paragraph(resume_text.replace('\n', '<br/>'), normal_style),
                            Spacer(1, 12),
                            Paragraph("Suggestions Applied:", styles['Heading2']),
                            Paragraph("<br/>".join(suggestions), normal_style),
                        ]
                        
                        doc.build(story)
                        pdf_bytes = buffer.getvalue()
                        buffer.close()
                        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
                        is_pdf = True
                        print("✅ PDF GENERATED")
                    except Exception as pdf_e:
                        print("❌ PDF GENERATION FAILED:", pdf_e)
                        # Fallback to text
                        pdf_base64 = base64.b64encode(enhanced_resume_text.encode('utf-8')).decode('utf-8')
                        is_pdf = False
                else:
                    # Fallback: Use text download
                    messages.warning(request, "AI analysis completed, but response format was unexpected. Using basic feedback. Check logs for details.")
                    score = 50
                    matched_keywords = ["Analysis completed"]
                    missing_keywords = ["Check job description"]
                    suggestions = ["Review and refine based on job requirements."]
                    pdf_base64 = base64.b64encode(enhanced_resume_text.encode('utf-8')).decode('utf-8')
                    is_pdf = False
                
                # Increment usage
                profile.resume_optimizations_this_month += 1
                profile.save()
                
                messages.success(request, "Resume analyzed successfully!")
            except Exception as e:
                messages.error(request, f"Error analyzing resume: {str(e)}. Please try again.")
        else:
            messages.error(request, "Please provide both job title and resume text.")
    
    context = {
        'profile': profile,
        'score': score,
        'matched_keywords': matched_keywords,
        'missing_keywords': missing_keywords,
        'suggestions': suggestions,
        'pdf_base64': pdf_base64,
        'is_pdf': is_pdf,  # To show PDF or text in template
        'resume_optimization_limit': resume_optimization_limit,
        'resume_percent': resume_percent,
        'job_title': request.POST.get('job_title', ''),
        'resume_text': request.POST.get('resume_text', ''),
    }
    return render(request, "resume_ai.html", context)

@login_required
def courses(request):
    profile = request.user.profile  
    courses = Course.objects.all() 
    return render(request, 'courses.html', {
        'courses': courses,
        'profile': profile,  
    })

@login_required
def profile(request):
    profile, created = Profile.objects.get_or_create(user=request.user)

    fields = [profile.phone, profile.bio, profile.education, profile.location,
              profile.experience, profile.skills, profile.resume]
    filled = sum(1 for f in fields if f)
    completion = int((filled / len(fields)) * 100) 
    
    mock_feedbacks = MockInterviewFeedback.objects.filter(appointment__application__user=request.user)
    subscription = getattr(request.user, "subscription", None)
    enrollments = Enrollment.objects.filter(profile=request.user.profile).select_related('course')[:5]  # Limit to 5 for display
    certificates = Certificate.objects.filter(enrollment__profile=request.user.profile)
    

    badges = UserBadge.objects.filter(user=request.user)
    
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {
        'form': form,
        'profile': profile,
        'completion': completion,
        'subscription': subscription,
        'mock_feedbacks': mock_feedbacks,
        'enrollments': enrollments,
        'certificates': certificates,
        'badges': badges, 
    })

@staff_member_required
def admin_job_applications(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    applications = JobApplication.objects.filter(job=job).order_by('-applied_at')

    if request.method == 'POST':
        for app in applications:
            status = request.POST.get(f'status_{app.id}')
            if status and status != app.status:
                app.status = status
                app.save()
        return redirect('admin_job_applications', job_id=job.id)

    return render(request, 'admin_job_applications.html', {'job': job, 'applications': applications})

@login_required
def application_tracker(request, application_id):
    application = get_object_or_404(
        JobApplication,
        id=application_id,
        user=request.user 
    )

    return render(request, 'application_tracker.html', {
        'application': application
    })

@staff_member_required
def admin_dashboard(request):
    courses = Course.objects.all()[:5]
    sla_compliance = Appointment.objects.filter(sla_complied=True).count() / Appointment.objects.count() * 100 if Appointment.objects.exists() else 0
    tier_conversions = Subscription.objects.values('plan_name').annotate(count=Count('id'))
    context = {
        'total_jobs': Job.objects.count(),
        'total_candidates': Profile.objects.count(),
        'total_applications': JobApplication.objects.count(),
        'pending_queries': SupportQuery.objects.filter(resolved=False).count(),
        'courses': courses,
        'sla_compliance': sla_compliance,
        'tier_conversions': tier_conversions,  
        'total_trainees': Profile.objects.filter(is_trainee=True).count(), 
    }
    return render(request, 'admin/dashboard.html', context)

@staff_member_required
def admin_candidates(request):
    q = request.GET.get('q', '')

    profiles = Profile.objects.select_related('user').filter(
        user__is_superuser=False,
        user__is_staff=False
    )

    if q:
        profiles = profiles.filter(
            Q(user__username__icontains=q) |
            Q(skills__icontains=q) |
            Q(location__icontains=q)
        )

    for profile in profiles:
        try:
            subscription = Subscription.objects.get(user=profile.user, active=True)
            profile.plan_name = subscription.plan_name
        except Subscription.DoesNotExist:
            profile.plan_name = None

    return render(request, 'admin/candidates.html', {'profiles': profiles, 'q': q})

@staff_member_required
def admin_candidate_detail(request, user_id):
    profile = get_object_or_404(
        Profile,
        user_id=user_id,
        user__is_superuser=False,
        user__is_staff=False
    )

    applications = JobApplication.objects.filter(user=profile.user)
    interactions = Interaction.objects.filter(application__user=profile.user)

    skills_list = [skill.strip() for skill in profile.skills.split(',')] if profile.skills else []

    limits = profile.get_limits()
    quota_data = {}

    def calculate_percent(used, limit):
        """Safely calculate percentage"""
        if limit is None:  # Unlimited
            return 100
        if limit == 0:
            return 0
        return min((used / limit) * 100, 100)

    # Applications
    applications_used = profile.applications_this_month()
    app_limit = limits["applications"]

    quota_data["applications_limit"] = app_limit
    quota_data["applications_percent"] = calculate_percent(applications_used, app_limit)

    # Chatbot
    chatbot_used = profile.chatbot_queries_this_month
    chatbot_limit = limits["chatbot"]

    quota_data["chatbot_limit"] = chatbot_limit
    quota_data["chatbot_percent"] = calculate_percent(chatbot_used, chatbot_limit)

    # Resume Optimization
    resume_used = profile.resume_optimizations_this_month
    resume_limit = limits["resume"]

    quota_data["resume_limit"] = resume_limit
    quota_data["resume_percent"] = calculate_percent(resume_used, resume_limit)

    # Consultant Sessions
    consultant_used = profile.consultant_sessions_this_month
    consultant_limit = limits["consultant_sessions"]

    quota_data["consultant_limit"] = consultant_limit
    quota_data["consultant_percent"] = calculate_percent(consultant_used, consultant_limit)

    # Mock Interviews
    mock_used = profile.mock_interviews_this_month
    mock_limit = limits["mock_interviews"]

    quota_data["mock_limit"] = mock_limit
    quota_data["mock_percent"] = calculate_percent(mock_used, mock_limit)

    # Course Enrollments
    courses_used = profile.courses_enrolled_this_month
    courses_limit = limits["courses"]

    quota_data["courses_limit"] = courses_limit
    quota_data["courses_percent"] = calculate_percent(courses_used, courses_limit)

    return render(request, 'admin/admin_candidate_detail.html', {
        'profile': profile,
        'applications': applications,
        'interactions': interactions,
        'skills_list': skills_list,
        'quota_data': quota_data,
    })

@recruiter_required
def schedule_interview(request, application_id):
    application = get_object_or_404(JobApplication, id=application_id)

    if request.method == "POST":
        scheduled_at = request.POST.get("scheduled_at")
        notes = request.POST.get("notes", "")

        Appointment.objects.create(
            application=application,
            scheduled_at=scheduled_at,
            notes=notes
        )
        application.status = "WAITING"
        application.save()

        Notification.objects.create(
            user=application.user,
            message=f"📅 Your interview for '{application.job.job_title}' has been scheduled on {scheduled_at}."
        )

        send_mail(
            subject="Interview Scheduled",
            message=f"Hi {application.user.username},\n\nYour interview for '{application.job.job_title}' has been scheduled on {scheduled_at}.\n\nNotes: {notes}\n\nBest,\nVCS Team",
            from_email="noreply@yourapp.com",
            recipient_list=[application.user.email],
            fail_silently=True,
        )

        return redirect("admin_candidate_detail", application.user.id)

    return render(request, "admin/schedule_interview.html", {"application": application})

@staff_member_required
def admin_queries(request):
    queries = SupportQuery.objects.all().order_by('-created_at')

    status_filter = request.GET.get('status', 'ALL')
    priority_filter = request.GET.get('priority', 'ALL')
    search_query = request.GET.get('search', '').strip()
    sort = request.GET.get('sort', 'NEWEST')

    if status_filter == 'OPEN':
        queries = queries.filter(resolved=False)
    elif status_filter == 'RESOLVED':
        queries = queries.filter(resolved=True)

    if priority_filter != 'ALL':
        queries = queries.filter(priority=priority_filter)

    if search_query:
        queries = queries.filter(
            Q(user__username__=search_query) |
            Q(subject__icontains=search_query)
        )

    if sort == 'OLDEST':
        queries = queries.order_by('created_at')
    else:
        queries = queries.order_by('-created_at')

    return render(request, 'admin/queries.html', {
        'queries': queries,
        'status_filter': status_filter,
        'priority_filter': priority_filter,
        'search_query': search_query,
        'sort': sort,
    })

@staff_member_required
def escalate_query(request, query_id):
    query = get_object_or_404(SupportQuery, id=query_id)
    query.priority = 'ESCALATED'
    query.save()
    return redirect('admin_queries')

@staff_member_required
def admin_jobs(request):
    q = request.GET.get('q', '')
    jobs = Job.objects.all().order_by('-posted_at')
    if q:
        jobs = jobs.filter(
            Q(job_title__icontains=q) |
            Q(company_name__icontains=q) |
            Q(location__icontains=q)
        )
    return render(request, 'admin/jobs.html', {'jobs': jobs})

@staff_member_required
def add_job(request):
    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            form.save()
            print("JOB SAVED")
        else:
            print("FORM ERRORS:", form.errors)
    return redirect('admin_jobs')

@staff_member_required
def edit_job(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    if request.method == "POST":
        form = JobForm(request.POST, instance=job)
        if form.is_valid():
            form.save()
    return redirect('admin_jobs')

@staff_member_required
def delete_job(request, job_id):
    job = get_object_or_404(Job, id=job_id)
    job.delete()
    return redirect('admin_jobs')

@staff_member_required
def admin_analytics(request):
    applications_by_status = JobApplication.objects.values('status').annotate(count=Count('id'))
    tier_usage = Profile.objects.values('is_pro', 'is_proplus').annotate(count=Count('id'))

    context = {
        'applications_by_status': applications_by_status,
        'tier_usage': tier_usage,
    }

    return render(request, 'admin/analytics.html', context)

@staff_member_required
def admin_application_detail(request, application_id):
    application = get_object_or_404(JobApplication, id=application_id)

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status:
            old_status = application.status
            application.status = new_status
            application.save()

            send_mail(
                subject="Job Application Status Update",
                message=f"Hi {application.user.username},\n\nThe status of your application for '{application.job.job_title}' at {application.job.company_name} has changed from '{old_status}' to '{new_status}'.\n\nCheck your dashboard for more details.\n\nBest,\nVCS Team",
                from_email="noreply@yourapp.com",
                recipient_list=[application.user.email],
                fail_silently=True,
            )

            return redirect('admin_application_detail', application_id=application.id)

    return render(request, 'admin_application_detail.html', {
        'application': application,
        'status_choices': JobApplication.STATUS_CHOICES
    })

@staff_member_required
def admin_applications_by_status(request, status):
    applications = JobApplication.objects.filter(status=status)\
        .select_related('user', 'job')

    return render(request, 'admin_applications_list.html', {
        'applications': applications,
        'status': status
    })

@login_required
def notification_processor(request):
    if request.user.is_authenticated:
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:5]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    else:
        notifications = []
        unread_count = 0

    return {
        'latest_notifications': notifications,
        'notification_count': unread_count,
    }

@login_required
def notifications(request):
    notes = Notification.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'notifications.html', {'notifications': notes})

@login_required
def mark_notification_read(request, notification_id):
    note = get_object_or_404(Notification, id=notification_id, user=request.user)
    note.is_read = True
    note.save()
    return redirect('notifications')

@login_required
def send_support_query(request):
    if request.method == "POST":
        subject = request.POST.get("subject")
        message = request.POST.get("message")
        priority = request.POST.get("priority")

        if not subject or not message:
            messages.error(request, "All fields are required.")
            return redirect("home")

        SupportQuery.objects.create(
            user=request.user,
            subject=subject,
            message=message,
            priority=priority
        )

        messages.success(request, "Your query has been sent successfully.")
        return redirect("home")

    return redirect("home")

@login_required
def reply_query(request, query_id):
    if not request.user.is_staff:
        return redirect('home')

    query = get_object_or_404(SupportQuery, id=query_id)

    if request.method == "POST":
        reply_text = request.POST.get("reply")

        query.reply = reply_text
        query.resolved = True
        query.save()

        Notification.objects.create(
            user=query.user,
            message=f"Admin replied to your query: {query.subject}"
        )

        send_mail(
            subject=f"Reply to Your Query: {query.subject}",
            message=f"Hi {query.user.username},\n\nAdmin Reply: {reply_text}\n\nYour query has been resolved.\n\nBest,\nVCS Team",
            from_email="noreply@yourapp.com",
            recipient_list=[query.user.email],
            fail_silently=True,
        )

    return redirect('admin_queries')

@staff_member_required
def mark_query_resolved(request, query_id):
    query = get_object_or_404(SupportQuery, id=query_id)
    query.resolved = True
    query.save()
    return redirect('admin_queries')

@csrf_exempt
@login_required
def payment_success(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

    data = json.loads(request.body)
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_signature = data.get('razorpay_signature')

    # Verify payment signature
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    params_dict = {
        'razorpay_order_id': razorpay_order_id,
        'razorpay_payment_id': razorpay_payment_id,
        'razorpay_signature': razorpay_signature
    }
    try:
        client.utility.verify_payment_signature(params_dict)
    except Exception as e:
        logger.error(f"Payment verification failed for user {request.user.username}: {str(e)}")
        return JsonResponse({'status': 'error', 'message': 'Payment verification failed'})

    # Retrieve plan details from session
    plan = request.session.get("plan")
    cycle = request.session.get("cycle")
    amount = Decimal(request.session.get("amount"))

    # Update profile and create subscription
    profile = request.user.profile
    if plan == "Pro":
        profile.is_pro = True
        profile.is_proplus = False
    elif plan == "Pro Plus":
        profile.is_pro = True
        profile.is_proplus = True
    profile.save()

    duration = 30 if cycle == "monthly" else 365
    subscription, _ = Subscription.objects.update_or_create(
        user=request.user,
        defaults={
            "plan_name": plan,
            "billing_cycle": cycle,
            "start_date": date.today(),
            "end_date": date.today() + timedelta(days=duration),
            "active": True
        }
    )

    # Create invoice
    invoice = Invoice.objects.create(
        user=request.user,
        subscription=subscription,
        amount=amount,
        paid=True
    )
    generate_invoice_pdf(invoice)

    # Clear session
    request.session.pop('plan', None)
    request.session.pop('cycle', None)
    request.session.pop('amount', None)
    request.session.pop('razorpay_order_id', None)

    return JsonResponse({"status": "success"})

def generate_invoice_pdf(invoice):
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.pdfgen import canvas
    from django.core.files.base import ContentFile
    from django.conf import settings
    import os

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=1,  # Center
        spaceAfter=20,
        textColor=colors.darkblue
    )
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=12,
        alignment=0,
        spaceAfter=10
    )
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,
        fontName='Helvetica-Bold'
    )
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontSize=10,
        alignment=0
    )
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=1,
        textColor=colors.gray
    )

    elements = []

    # Company Header with Logo
    logo_path = os.path.join(settings.STATIC_ROOT, 'logo.png')  # Replace with your logo path
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=1*inch, height=1*inch)
        elements.append(logo)
    elements.append(Spacer(1, 0.2*inch))

    company_info = """
    <b>VCS Career Services Pvt. Ltd.</b><br/>
    123 Career Lane, Tech City<br/>
    Bangalore, Karnataka 560001<br/>
    India<br/>
    GSTIN: 29ABCDE1234F1Z5<br/>
    Email: support@vcs.com | Phone: +91-9876543210
    """
    elements.append(Paragraph(company_info, header_style))
    elements.append(Spacer(1, 0.5*inch))

    # Invoice Title
    elements.append(Paragraph("INVOICE", title_style))
    elements.append(Spacer(1, 0.3*inch))

    # Invoice Details
    invoice_details = f"""
    <b>Invoice Number:</b> {invoice.invoice_number}<br/>
    <b>Invoice Date:</b> {invoice.date.strftime('%d-%m-%Y')}<br/>
    <b>Due Date:</b> {invoice.date.strftime('%d-%m-%Y')} (Immediate)<br/>
    <b>Payment Status:</b> {'Paid' if invoice.paid else 'Pending'}
    """
    elements.append(Paragraph(invoice_details, header_style))
    elements.append(Spacer(1, 0.3*inch))

    # Bill To Section
    bill_to = f"""
    <b>Bill To:</b><br/>
    {invoice.user.username}<br/>
    {invoice.user.email}<br/>
    (Subscription User)
    """
    elements.append(Paragraph(bill_to, header_style))
    elements.append(Spacer(1, 0.3*inch))

    # Itemized Table
    data = [
        ['Description', 'Quantity', 'Unit Price', 'Total'],
        [f"{invoice.subscription.plan_name} Subscription ({invoice.subscription.billing_cycle})", '1', f"₹{invoice.amount}", f"₹{invoice.amount}"],
    ]
    table = Table(data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.3*inch))

    # Totals
    subtotal = invoice.amount
    gst = subtotal * Decimal('0.18') # 18% GST (adjust as needed)
    total = subtotal + gst

    totals_data = [
        ['', 'Subtotal:', f"₹{subtotal}"],
        ['', 'GST (18%):', f"₹{gst:.2f}"],
        ['', 'Total:', f"₹{total:.2f}"],
    ]
    totals_table = Table(totals_data, colWidths=[3*inch, 1.5*inch, 1.5*inch])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (1, 0), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (1, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(totals_table)
    elements.append(Spacer(1, 0.5*inch))

    # Footer
    footer_text = """
    Thank you for choosing VCS Career Services!<br/>
    Payment Terms: Immediate payment required. For queries, contact support@vcs.com.<br/>
    This is a computer-generated invoice and does not require a signature.
    """
    elements.append(Paragraph(footer_text, footer_style))

    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    invoice.file.save(
        f"{invoice.invoice_number}.pdf",
        ContentFile(buffer.read())
    )
    buffer.close()

@recruiter_required
def consultant_dashboard(request):
    applications = JobApplication.objects.select_related('user', 'job').order_by('-applied_at')[:10]  # Limit to 10 for performance
    return render(request, 'admin/consultant_dashboard.html', {'applications': applications})

def appointment_list(request):
    appt_type = request.GET.get("type")
    search_query = request.GET.get("search", "")

    appointments = Appointment.objects.all()

    if appt_type:
        appointments = appointments.filter(appointment_type=appt_type)

    if search_query:
        appointments = appointments.filter(application__user__username__icontains=search_query)

    template_name = {
        'INTERVIEW': 'admin/interview_list.html',
        'ONE_ON_ONE': 'admin/one_on_one_list.html',
    }.get(appt_type)

    users = User.objects.filter(
        profile__isnull=False,
        is_superuser=False
    ).filter(
        Q(profile__is_pro=True) | Q(profile__is_proplus=True)
    ).select_related('profile')

    todays_slots, created = InterviewSlot.objects.get_or_create(date=date.today())
    context = {
        "appointments": appointments,
        "appt_type": appt_type,
        "search_query": search_query,
        "users": users,
        'todays_slots': todays_slots,
    }
    return render(request, template_name, context)

@recruiter_required
def create_interview_appointment(request):
    try:
        return _create_appointment(request, 'INTERVIEW')
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@recruiter_required
def create_one_on_one_appointment(request):
    return _create_appointment(request, 'ONE_ON_ONE')

def _create_appointment(request, appointment_type):
    form = AppointmentForm(request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            user = form.cleaned_data['user']
            application = JobApplication.objects.filter(user=user).first()
            
            scheduled_date = form.cleaned_data['scheduled_at'].date()
            slot, created = InterviewSlot.objects.get_or_create(date=scheduled_date)
            if not slot.can_schedule():
                return JsonResponse({'success': False, 'error': 'No available slots for this date.'})
            
            if not application:
                first_job = Job.objects.first()
                if not first_job:
                    return JsonResponse({'success': False, 'error': 'No jobs available to create application.'})
                application = JobApplication.objects.create(user=user, job=first_job)

            appointment = form.save(commit=False)
            appointment.application = application
            appointment.consultant = request.user
            appointment.appointment_type = appointment_type
            appointment.set_sla()  # UPDATED: Set SLA
            appointment.save()  

            slot.increment_slots()

            calendar_event = CalendarEvent.objects.create(
                title=f"{appointment_type.replace('_',' ')} - {appointment.application.user.username}",
                user=appointment.application.user,
                start_time=appointment.scheduled_at,
                end_time=appointment.scheduled_at + timezone.timedelta(hours=1),  
                related_appointment=appointment
            )

            Notification.objects.create(
                user=appointment.application.user,
                message=f"Interview scheduled for {appointment.scheduled_at}."
            )
            
            Interaction.objects.create(
                application=appointment.application,
                admin=request.user,
                message=f"{appointment_type.replace('_',' ')} scheduled on {appointment.scheduled_at}"
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True})
            return redirect(reverse('appointment_list') + f'?type={appointment_type}')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'errors': form.errors})
            
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('admin/appointment_form.html', {'form': form}, request)
        return JsonResponse({'html': html})

    return redirect(reverse('appointment_list') + f'?type={appointment_type}')

@recruiter_required
def edit_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    form = AppointmentForm(request.POST or None, instance=appointment)

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data['user'] 
        application = JobApplication.objects.filter(user=user).first()
        if not application:
            first_job = Job.objects.first()
            application = JobApplication.objects.create(user=user, job=first_job)

        form.instance.application = application 
        form.save()

        Interaction.objects.create(
            application=appointment.application,
            admin=request.user,
            message=f"{appointment.appointment_type} updated on {appointment.scheduled_at}"
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        return redirect(reverse('appointment_list') + f'?type={appointment.appointment_type}')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('admin/appointment_form.html', {'form': form}, request)
        return JsonResponse({'html': html})
    return redirect(reverse('appointment_list') + f'?type={appointment.appointment_type}')

@recruiter_required
def postpone_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    form = PostponeAppointmentForm(request.POST or None, instance=appointment)

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data.get('user')
        if user:
            application = JobApplication.objects.filter(user=user).first()
            if not application:
                first_job = Job.objects.first()
                application = JobApplication.objects.create(user=user, job=first_job)
            form.instance.application = application
        form.save()

        if appointment.scheduled_at and (appointment.scheduled_at - now()).total_seconds() > 86400:
            if appointment.is_mock_interview:
                appointment.application.user.profile.decrement_mock_interviews()
            else:
                slot = InterviewSlot.objects.filter(date=appointment.scheduled_at.date()).first()
                if slot:
                    slot.decrement_slots()

        if appointment.is_mock_interview and (appointment.scheduled_at - now()).total_seconds() > 86400:  # 24h
            appointment.application.user.profile.decrement_mock_interviews()

        Interaction.objects.create(
            application=appointment.application,
            admin=request.user,
            message=f"{appointment.appointment_type} postponed to {appointment.scheduled_at}"
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        return JsonResponse({"success": True})

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        html = render_to_string('admin/postpone_appointment_form.html', {'form': form}, request)
        return JsonResponse({'html': html})
    
    return redirect(reverse('appointment_list') + f'?type={appointment.appointment_type}')

@recruiter_required
def update_appointment_status(request, appointment_id, status):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    if status.upper() in ['SCHEDULED', 'DONE', 'POSTPONED']:
        appointment.status = status.upper()
        appointment.save()

        Interaction.objects.create(
            application=appointment.application,
            admin=request.user,
            message=f"{appointment.appointment_type} marked as {status}"
        )

    return redirect(reverse ('appointment_list') + f'?type={appointment.appointment_type}')

@recruiter_required
def upload_mock_feedback(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, is_mock_interview=True)
    feedback, created = MockInterviewFeedback.objects.get_or_create(appointment=appointment)

    if request.method == 'POST':
        form = MockInterviewFeedbackForm(request.POST, request.FILES, instance=feedback)
        if form.is_valid():
            form.instance.uploaded_by = request.user
            form.save()
            
            Notification.objects.create(
                user=appointment.application.user,
                message="Your mock interview feedback is ready. Check your profile."
            )

            send_mail(
                subject="Mock Interview Feedback Available",
                message="Your mock interview feedback report and improvement plan are now available. Log in to view them.",
                from_email="noreply@yourapp.com",
                recipient_list=[appointment.application.user.email],
                fail_silently=True,
            )

            if appointment.status != 'DONE':
                appointment.status = 'DONE'
                appointment.save()

            return redirect(reverse('appointment_list') + '?appt_type=INTERVIEW')

    else:
        form = MockInterviewFeedbackForm(instance=feedback)

    return render(request, 'admin/upload_feedback.html', {'form': form, 'appointment': appointment})

@recruiter_required
def mark_done_with_feedback(request, appointment_id):
    if request.method == 'POST':
        appointment = get_object_or_404(Appointment, id=appointment_id)
        feedback_notes = request.POST.get('feedback_notes', '').strip()  # Optional, defaults to empty
        
        if feedback_notes:
            appointment.notes = (appointment.notes or '') + f"\n\nFeedback: {feedback_notes}"
        
        appointment.status = 'DONE'
        appointment.save()
        
        Notification.objects.create(
            user=appointment.application.user,
            message="Your interview has been marked as completed. Check for feedback."
        )
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=400)

@recruiter_required 
def appointment_list_api(request):
    q = request.GET.get("q", "")
    apptype = request.GET.get("type", "")
    status = request.GET.get("status", "")
    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")

    appointments = Appointment.objects.select_related(
        "application__user", "application__job"
    ).order_by("scheduled_at")

    if q:
        appointments = appointments.filter(
            application__user__username__icontains=q
        )

    if apptype:
        appointments = appointments.filter(appointment_type=apptype)

    if status:
        appointments = appointments.filter(status=status)

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            appointments = appointments.filter(scheduled_at__date__gte=start_date)
        except ValueError:
            pass 

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            appointments = appointments.filter(scheduled_at__date__lte=end_date)
        except ValueError:
            pass  

    data = []
    for a in appointments:
        data.append({
            "id": a.id,
            "candidate": a.application.user.username,
            "job": a.application.job.job_title,
            "type": a.appointment_type,
            "status": a.status,
            "datetime": a.scheduled_at.strftime("%d %b %Y %H:%M"),
            "notes": a.notes,
            "interview_type": a.interview_type or "N/A",
            "target_role": a.target_role or "N/A", 
            "is_mock": a.is_mock_interview,
        })

    return JsonResponse(data, safe=False)

@recruiter_required
def appointment_view(request, appointment_id):
    if request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        appointment = get_object_or_404(Appointment, id=appointment_id)
        feedback = getattr(appointment, 'feedback', None) 
        feedback_notes = feedback.improvement_plan if feedback else 'N/A'
        
        data = {
            'candidate': appointment.application.user.username if appointment.application else 'N/A',
            'interview_type': appointment.interview_type or 'N/A',
            'target_role': appointment.target_role or 'N/A',
            'scheduled_at': appointment.scheduled_at.strftime('%Y-%m-%d %H:%M') if appointment.scheduled_at else 'N/A',
            'status': appointment.status,
            'notes': appointment.notes or 'N/A',
            'feedback_notes': feedback_notes,
        }
        return JsonResponse(data)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@recruiter_required
def view_feedback(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, is_mock_interview=True)
    feedback = get_object_or_404(MockInterviewFeedback, appointment=appointment)
    
    return render(request, 'admin/view_feedback.html', {
        'appointment': appointment,
        'feedback': feedback,
    })

@login_required
def user_feedbacks(request):
    appointments = Appointment.objects.filter(
        application__user=request.user,
        status='DONE'
    ).select_related('feedback').order_by('-scheduled_at')
    
    return render(request, 'user_feedbacks.html', {
        'appointments': appointments,
    })

@recruiter_required
def admin_calendar(request):
    return render(request, "admin/calendar.html")

@recruiter_required
def calendar_events(request):
    events = CalendarEvent.objects.select_related('related_appointment')
    print(f"Fetching {events.count()} calendar events")
    data = []
    for e in events:
        data.append({
            "id": e.id,
            "title": e.title,
            "start": e.start_time.isoformat(),
            "end": e.end_time.isoformat(),
            "appointment_id": e.related_appointment.id if e.related_appointment else None,  # Optional: include related appointment
        })

    return JsonResponse(data, safe=False)

@login_required
def enroll_course(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    profile = request.user.profile

    if course.tier_required == 'PRO_PLUS' and not profile.is_proplus:
        messages.error(request, "This course requires Pro Plus subscription.")
        return redirect('courses')
    if course.tier_required == 'PRO' and not (profile.is_pro or profile.is_proplus):
        messages.error(request, "This course requires Pro subscription.")

    if course.max_enrollments > 0 and Enrollment.objects.filter(profile=request.user.profile, course=course).count() >= course.max_enrollments:  # Fixed: Use 'profile'
        messages.error(request, "Enrollment limit reached for this course.")
        return redirect('courses')

    enrollment, created = Enrollment.objects.get_or_create(profile=request.user.profile, course=course)  # Fixed: Use 'profile'
    if created:
        enrollment.current_stage = 'ENROLLED' 
        enrollment.save()

        for step in course.progressstep_set.all():
            UserProgress.objects.create(enrollment=enrollment, step=step)
        messages.success(request, "Enrolled successfully!")
    return redirect('training_progress')

@login_required
def training_progress(request):
    enrollments = Enrollment.objects.filter(profile=request.user.profile).select_related('course')
    return render(request, 'training_progress.html', {'enrollments': enrollments})

@staff_member_required
def admin_course_details(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    enrollments = Enrollment.objects.filter(course=course).select_related('profile__user')  
    return render(request, 'admin/admin_course_details.html', {'course': course, 'enrollments': enrollments})

@staff_member_required
def admin_user_progress(request, enrollment_id):
    enrollment = get_object_or_404(Enrollment, id=enrollment_id)
    progresses = UserProgress.objects.filter(enrollment=enrollment).select_related('step')
    
    progress_percentage = enrollment.get_stage_number() * 20 
    
    if request.method == 'POST':
        for progress in progresses:
            status = request.POST.get(f'status_{progress.id}')
            if status in ['NOT_STARTED', 'IN_PROGRESS', 'COMPLETED']:
                progress.status = status
                progress.save()

        if all(p.status == 'COMPLETED' for p in progresses):
            if enrollment.current_stage == 1:
                enrollment.current_stage = 2  
                enrollment.status = 'STARTED'
            elif enrollment.current_stage == 2:  
                enrollment.current_stage = 3  
                enrollment.status = 'EXAMS'
            elif enrollment.current_stage == 3: 
                enrollment.current_stage = 4
                enrollment.status = 'INTERVIEW'
            elif enrollment.current_stage == 4: 
                enrollment.current_stage = 5
                enrollment.status = 'CERTIFIED'
                enrollment.completed_at = timezone.now()
                if enrollment.course.has_certificate:
                    Certificate.objects.get_or_create(enrollment=enrollment)
            enrollment.save()
        messages.success(request, "Progress updated.")
        return redirect('admin_user_progress', enrollment_id=enrollment_id)
    
    return render(request, 'admin/admin_user_progress.html', {
        'enrollment': enrollment, 
        'progresses': progresses,
        'progress_percentage': progress_percentage
    })

@login_required
def training_dashboard(request):
    profile = request.user.profile
    enrollments = Enrollment.objects.filter(profile=request.user.profile)
    certificates = Certificate.objects.filter(enrollment__profile=request.user.profile, enrollment__status='CERTIFIED')
    available_courses = Course.objects.filter(tier_required__in=['FREE'] if not profile.is_pro and not profile.is_proplus else ['FREE', 'PRO'] if profile.is_pro else ['FREE', 'PRO', 'PRO_PLUS'])
    completed_count = enrollments.filter(status='CERTIFIED').count()
    
    return render(request, 'training_dashboard.html', {
        'enrollments': enrollments,
        'certificates': certificates,
        'available_courses': available_courses,
        'completed_count': completed_count,
    })

@staff_member_required
def sync_progress(request):
    messages.success(request, "Progress synced from VTS.")
    return redirect('admin_dashboard')

@staff_member_required
def admin_courses(request):
    courses = Course.objects.all()
    return render(request, 'admin/admin_courses.html', {'courses': courses})

@staff_member_required
def admin_add_course(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course added successfully!')
            return redirect('admin_courses')
    else:
        form = CourseForm()
    return render(request, 'admin/admin_add_course.html', {'form': form})

def award_badges(user):
    profile = user.profile
    badges = Badge.objects.all()
    for badge in badges:
        if eval(badge.criteria): 
            UserBadge.objects.get_or_create(user=user, badge=badge)

@login_required
def schedule_mock_interview(request):
    try:
        profile = request.user.profile
        if not profile.is_proplus:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'This feature is only available for Pro Plus users.'})
            messages.error(request, "This feature is only available for Pro Plus users.")
            return redirect('profile')

        if not profile.can_schedule_mock_interview():
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': 'already slot full'})
            messages.error(request, "already slot full")
            return redirect('profile')
        
        if request.method == 'POST':
            form = MockInterviewForm(request.POST, user=request.user)
            if form.is_valid():
                appointment = form.save(commit=False)
                appointment.application = JobApplication.objects.filter(user=request.user).first()
                
                if not appointment.application:
                    first_job = Job.objects.first()
                    if first_job:
                        appointment.application = JobApplication.objects.create(user=request.user, job=first_job)
                    else:
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': 'No jobs available to create an application.'})
                        messages.error(request, "No jobs available to create an application.")
                        return redirect('profile')
                
                appointment.consultant = profile.dedicated_consultant or User.objects.filter(is_staff=True).first()
                appointment.appointment_type = 'INTERVIEW'
                appointment.is_mock_interview = True
                appointment.video_link = "https://zoom.us/j/example"
                appointment.save()

                profile.increment_mock_interviews()

                CalendarEvent.objects.create(
                    title=f"Mock Interview - {appointment.interview_type}",
                    user=request.user,
                    start_time=appointment.scheduled_at,
                    end_time=appointment.scheduled_at + timedelta(hours=1),
                    related_appointment=appointment
                )

                Notification.objects.create(
                    user=request.user,
                    message=f"Mock interview scheduled for {appointment.scheduled_at}. Video Link: {appointment.video_link}"
                )

                send_mail(
                    subject="Mock Interview Scheduled",
                    message=f"Your mock interview is scheduled for {appointment.scheduled_at}. Video Link: {appointment.video_link}. Type: {appointment.interview_type}, Role: {appointment.target_role}",
                    from_email="noreply@yourapp.com",
                    recipient_list=[request.user.email],
                    fail_silently=True,
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True})
                messages.success(request, "Mock interview scheduled successfully! Check your email for details.")
                return redirect('profile')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'error': 'Form validation failed.'})
                messages.error(request, "Form validation failed.")
                return redirect('profile')
        else:
            form = MockInterviewForm(user=request.user)

        return render(request, 'schedule_mock_interview.html', {
            'form': form,
            'remaining_quota': profile.mock_interviews_remaining(),
        })
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@shared_task
def reset_monthly_quotas():
    now = timezone.now()
    if now.day == 1:
        Profile.objects.update(
            mock_interviews_this_month=0,
            resume_optimizations_this_month=0,
            chatbot_queries_this_month=0,
            consultant_sessions_this_month=0,
            applications_this_month=0
        )

@shared_task
def check_sla_violations():
    overdue = Appointment.objects.filter(sla_due__lt=timezone.now(), sla_complied=False)
    for appt in overdue:
        send_mail("SLA Violation", f"Appointment {appt.id} is overdue.", 'noreply@yourapp.com', [appt.consultant.email])

@shared_task
def trigger_annual_reviews():
    now = timezone.now()
    proplus_users = Profile.objects.filter(is_proplus=True, user__subscription__end_date__year=now.year)
    for profile in proplus_users:
        if not AnnualReview.objects.filter(user=profile.user, year=now.year).exists():
            Appointment.objects.create(
                application=JobApplication.objects.filter(user=profile.user).first(),
                appointment_type='ONE_ON_ONE',
                notes="Annual Outcome Review"
            )


@staff_member_required
def admin_consultant_tracking(request):
    search_query = request.GET.get('search', '').strip()
    tier_filter = request.GET.get('tier', '')

    profiles = Profile.objects.select_related('user').filter(
        user__is_superuser=False,
        user__is_staff=False,
        is_pro=True
    )

    if search_query:
        profiles = profiles.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(user__username__icontains=search_query)
        )

    if tier_filter == 'pro':
        profiles = profiles.filter(is_pro=True, is_proplus=False)
    elif tier_filter == 'proplus':
        profiles = profiles.filter(is_proplus=True)

    profiles = profiles.order_by('-consultant_hours_used_this_month')

    consultant_data = []

    for profile in profiles:
        limits = profile.get_limits()

        session_limit = limits["consultant_sessions"]
        limit_hours = float(session_limit) if session_limit is not None else None
        used_hours = float(profile.consultant_hours_used_this_month)

        if limit_hours is None:
            percent = 100
        elif limit_hours == 0:
            percent = 0
        else:
            percent = min((used_hours / limit_hours) * 100, 100)

        consultant_data.append({
            'profile': profile,
            'limit_hours': limit_hours,
            'used_hours': used_hours,
            'percent': percent,
            'tier': profile.tier,
        })

    total_hours = sum(data['used_hours'] for data in consultant_data)
    avg_usage = total_hours / len(consultant_data) if consultant_data else 0

    paginator = Paginator(consultant_data, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'admin/admin_consultant_tracking.html', {
        'page_obj': page_obj,
        'total_hours': total_hours,
        'avg_usage': avg_usage,
        'search_query': search_query,
        'tier_filter': tier_filter,
    })


@staff_member_required
def admin_create_trainee(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        course = request.POST.get('course')
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        trainee_plan = request.POST.get('trainee_plan')
        
        if User.objects.filter(username=username).exists():
            error_msg = 'Username already exists.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('admin_dashboard')
        
        # Create user
        user = User.objects.create_user(username=username, password=password, email=email, first_name=first_name, last_name=last_name)
        
        # Create profile and set plan
        profile, created = Profile.objects.get_or_create(user=user)
        profile.is_trainee = True
        profile.course = course
        profile.trainee_plan = trainee_plan
        profile.save()
        

        success_msg = f"Trainee {username} created successfully."
        messages.success(request, success_msg)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        return redirect('admin_trainees')
    
    # For modal rendering
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'admin/admin_create_trainee_modal.html')
    return redirect('admin_dashboard')

@staff_member_required
def admin_trainees(request):
    trainees = Profile.objects.filter(is_trainee=True).select_related('user')
    return render(request, 'admin/admin_trainees.html', {'trainees': trainees})

@staff_member_required
def admin_edit_trainee(request, user_id):
    profile = get_object_or_404(Profile, user_id=user_id, is_trainee=True)
    if request.method == 'POST':
        profile.user.first_name = request.POST.get('first_name')
        profile.user.last_name = request.POST.get('last_name')
        profile.course = request.POST.get('course')
        profile.user.username = request.POST.get('username')
        profile.user.email = request.POST.get('email')
        profile.trainee_plan = request.POST.get('trainee_plan')
        if request.POST.get('password'):
            profile.user.set_password(request.POST.get('password'))
        profile.user.save()
        profile.save()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True})
        messages.success(request, "Trainee updated successfully.")
        return redirect('admin_trainees')
    return render(request, 'admin/admin_edit_trainee.html', {'profile': profile})


@staff_member_required
def admin_delete_trainee(request, user_id):
    if request.method == 'POST':
        profile = get_object_or_404(Profile, user_id=user_id, is_trainee=True)
        profile.user.delete()  # Deletes user and profile
        messages.success(request, "Trainee deleted successfully.")
    return redirect('admin_trainees')

def trainee_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        
        user = authenticate(request, username=username, password=password)
        if user and hasattr(user, 'profile') and user.profile.is_trainee:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, "Invalid credentials or not a trainee account.")
    return render(request, "trainee_login.html")