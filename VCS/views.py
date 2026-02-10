from django.shortcuts import render,redirect,get_object_or_404
from django.contrib.auth import authenticate, login
from .forms import (SignupForm,ProfileForm,JobApplicationForm,
                    JobForm,AppointmentForm,PostponeAppointmentForm,
                    MockInterviewForm,MockInterviewFeedbackForm,
                    CourseForm,)
from .models import (ChatQuestionAnswer,Invoice, CandidateChat,
                     Job,Profile,Subscription,Course,
                     JobApplication,Appointment,Interaction,
                     SupportQuery,Notification,CalendarEvent,
                     MockInterviewFeedback,InterviewSlot,
                     Enrollment,Certificate,UserProgress,)
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
PRO_CHAT_LIMIT = 100


@csrf_exempt
@login_required
def chatbot_api(request):
    if request.method != 'POST':
        return JsonResponse({'reply': "Invalid request."})
    try:
        data = json.loads(request.body)
        user_question = data.get("message", "").strip()
    except Exception:
        return JsonResponse({"reply": "Invalid JSON data"}, status=400)

    if not user_question:
        return JsonResponse({'reply': "Please enter a question."})
    
    profile, _ = Profile.objects.get_or_create(user=request.user)
    user_chat_count = CandidateChat.objects.filter(candidate=request.user).count()

    if not profile.is_pro and not profile.is_proplus:
        if user_chat_count >= FREE_CHAT_LIMIT:
            return JsonResponse({
                'reply': "⚠️ You have reached your free limit of 10 questions. Please upgrade to Pro.",
                'upgrade_required': True
            })

    elif profile.is_pro and not profile.is_proplus:
        if user_chat_count >= PRO_CHAT_LIMIT:
            return JsonResponse({
                'reply': "⚠️ You have reached your Pro limit of 100 questions. Please upgrade to Pro Plus for unlimited access.",
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
        
        return JsonResponse({
            'reply': answer,
            'source': source
        })
    else:
        try:
            faq = ChatQuestionAnswer.objects.get(question__iexact=user_question)
            answer = faq.answer
            source = "db"
        except ChatQuestionAnswer.DoesNotExist:
            answer = ask_gemini(user_question)
            source = "gemini"

        CandidateChat.objects.create(
            candidate=request.user,
            question=user_question,
            answer=json.dumps(answer) 
        )

        return JsonResponse({
            'reply': answer,
            'source': source
        })



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
        user_chat_count = CandidateChat.objects.filter(candidate=request.user).count()

        if not profile.is_pro and user_chat_count >= 10:
            return JsonResponse({
                'error': "You have reached your free limit of 10 questions. Upgrade to Pro.",
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


def user_login(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            if user.is_superuser or user.is_staff:
                return redirect('admin_dashboard')
            else:
                return redirect('home')
        else:
            return render(request, "registration/login.html", {"error": "Invalid credentials. Please sign up first."})

    return render(request, "registration/login.html")



def signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            user = authenticate(username=user.username, password=form.cleaned_data['password'])
            if user is not None:
                login(request, user) 
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

        profile = Profile.objects.get(user=request.user)
        applications_used = profile.applications_this_month()
        applications_limit = profile.application_limit()

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

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {'form': form, 'profile': profile})



@login_required
def upgrade_plan(request):
    profile = Profile.objects.get(user=request.user)
    invoice_url = None

    if request.method == "POST":
        plan = request.POST.get("plan")

        if plan == "pro_monthly":
            profile.is_pro = True
            profile.is_proplus = False
            plan_name = "Pro"
            billing_cycle = "monthly"
            duration_days = 30

        elif plan == "pro_yearly":
            profile.is_pro = True
            profile.is_proplus = False
            plan_name = "Pro"
            billing_cycle = "yearly"
            duration_days = 365

        elif plan == "pro_plus":
            profile.is_pro = True
            profile.is_proplus = True
            plan_name = "Pro Plus"
            billing_cycle = "yearly"
            duration_days = 365

        else:
            return redirect("upgrade_plan")

        profile.save()

        # Update or create subscription
        subscription, created = Subscription.objects.update_or_create(
            user=request.user,
            defaults={
                "plan_name": plan_name,
                "billing_cycle": billing_cycle,
                "start_date": date.today(),
                "end_date": date.today() + timedelta(days=duration_days),
                "active": True
            }
        )

        # Create new invoice (mark as paid after upgrade)
        invoice=Invoice.objects.create(
            user=request.user,
            subscription=subscription,
            amount=subscription.price_amount,
            paid=True
        )

        generate_invoice_pdf(invoice)
        invoice_url = invoice.file.url

        return redirect("subscription")

    return render(request, "upgrade.html",{
            "invoice_url": invoice_url
        })



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
    profile = request.user.profile
    suggestions = []
    score = None
    matched_keywords = []
    missing_keywords = []
    job_title = ""

    if request.method == "POST":
        resume_text = request.POST.get("resume_text", "").strip()
        job_title = request.POST.get("job_title", "").strip()

        if resume_text and job_title:
            keyword_prompt = f"Extract a list of 5-10 key skills, technologies, and keywords relevant to the job title '{job_title}'. Provide them as a comma-separated list."
            keyword_response = ask_gemini(keyword_prompt)
            
            if keyword_response and keyword_response != "⚠️ AI service is temporarily unavailable.":
                keywords = [kw.strip().lower() for kw in keyword_response.split(',') if kw.strip()]
            else:
                keywords = ["python", "django", "sql", "project", "experience", "skills"]

            resume_lower = resume_text.lower()
            matched_keywords = [k for k in keywords if k in resume_lower]
            missing_keywords = [k for k in keywords if k not in resume_lower]

            score = int((len(matched_keywords) / len(keywords)) * 100) if keywords else 0

            suggestion_prompt = f"Analyze the following resume text for the job '{job_title}' and provide up to 10 concise suggestions for improvement: {resume_text}"
            ai_response = ask_gemini(suggestion_prompt)

            if ai_response and ai_response != "⚠️ AI service is temporarily unavailable.":
                suggestions = [line.strip() for line in ai_response.split('\n') if line.strip()]
            else:
                suggestions = [
                    "Add more measurable achievements relevant to the job.",
                    "Include relevant job keywords in your resume.",
                    "Mention projects with tools and technologies used.",
                    "Improve formatting for readability.",
                    "Highlight certifications and training courses."
                ]

    return render(request, "resume_ai.html", {
        "profile": profile,
        "suggestions": suggestions,
        "score": score,
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "job_title": job_title
    })


def courses(request):
    profile = request.user.profile if request.user.is_authenticated else None
    courses = Course.objects.all()
    if profile:
        if not profile.is_pro and not profile.is_proplus:
            courses = courses.filter(tier_required='FREE')
        elif profile.is_pro and not profile.is_proplus:
            courses = courses.filter(tier_required__in=['FREE', 'PRO'])
    return render(request, 'courses.html', {'courses': courses})



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
    context = {
        'total_jobs': Job.objects.count(),
        'total_candidates': Profile.objects.count(),
        'total_applications': JobApplication.objects.count(),
        'pending_queries': SupportQuery.objects.filter(resolved=False).count(),
        'courses': courses,
    }
    return render(request, 'admin/dashboard.html', context)


@staff_member_required
def admin_candidates(request):
    q = request.GET.get('q', '')

    # Get all profiles except staff/superusers
    profiles = Profile.objects.select_related('user').filter(
        user__is_superuser=False,
        user__is_staff=False
    )

    # Filter by search query
    if q:
        profiles = profiles.filter(
            Q(user__username__icontains=q) |
            Q(skills__icontains=q) |
            Q(location__icontains=q)
        )

    # Attach plan_name to each profile
    for profile in profiles:
        try:
            subscription = Subscription.objects.get(user=profile.user, active=True)
            profile.plan_name = subscription.plan_name  # "Pro" or "Pro Plus"
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

    return render(request, 'admin/candidate_detail.html', {
        'profile': profile,
        'applications': applications,
        'interactions': interactions
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
            Q(user__username__icontains=search_query) |
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

    context = {
        'applications_by_status': applications_by_status,
    }

    return render(request, 'admin/analytics.html', context)


@staff_member_required
def admin_application_detail(request, application_id):
    application = get_object_or_404(JobApplication, id=application_id)

    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status:
            application.status = new_status
            application.save()
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

    return redirect('admin_queries')

@staff_member_required
def mark_query_resolved(request, query_id):
    query = get_object_or_404(SupportQuery, id=query_id)
    query.resolved = True
    query.save()
    return redirect('admin_queries')






import razorpay
from io import BytesIO
from django.core.files.base import ContentFile
from reportlab.pdfgen import canvas
from decimal import Decimal




# client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


# @login_required
# def create_razorpay_order(request):
#     data = json.loads(request.body)
#     plan = data["plan"]            # Pro / Pro Plus
#     cycle = data["cycle"]          # monthly / yearly

#     subscription = Subscription.objects.get(user=request.user)
#     subscription.plan_name = plan
#     subscription.billing_cycle = cycle

#     amount = int(subscription.price_amount * 100)  # paise

#     order = client.order.create({
#         "amount": amount,
#         "currency": "INR",
#         "payment_capture": 1
#     })

#     request.session["plan"] = plan
#     request.session["cycle"] = cycle
#     request.session["amount"] = str(subscription.price_amount)

#     return JsonResponse({
#         "order_id": order["id"],
#         "amount": amount
#     })


# ---------- PAYMENT SUCCESS ----------
@csrf_exempt
@login_required
def payment_success(request):
    data = json.loads(request.body)

    plan = request.session.get("plan")
    cycle = request.session.get("cycle")
    amount = Decimal(request.session.get("amount"))

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

    invoice = Invoice.objects.create(
        user=request.user,
        subscription=subscription,
        amount=amount,
        paid=True
    )

    generate_invoice_pdf(invoice)

    return JsonResponse({"status": "success"})


# ---------- PDF GENERATOR ----------
def generate_invoice_pdf(invoice):
    buffer = BytesIO()
    p = canvas.Canvas(buffer)

    p.drawString(100, 800, "SUBSCRIPTION INVOICE")
    p.drawString(100, 770, f"Invoice No: {invoice.invoice_number}")
    p.drawString(100, 740, f"User: {invoice.user.username}")
    p.drawString(100, 710, f"Plan: {invoice.subscription.plan_name}")
    p.drawString(100, 680, f"Billing Cycle: {invoice.subscription.billing_cycle}")
    p.drawString(100, 650, f"Amount: ₹{invoice.amount}")
    p.drawString(100, 620, f"Date: {invoice.date.strftime('%d-%m-%Y')}")

    p.showPage()
    p.save()

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
            appointment.save()  

            slot.increment_slots()

            calendar_event = CalendarEvent.objects.create(
                title=f"{appointment_type.replace('_',' ')} - {appointment.application.user.username}",
                user=appointment.application.user,
                start_time=appointment.scheduled_at,
                end_time=appointment.scheduled_at + timezone.timedelta(hours=1),  
                related_appointment=appointment
            )
            print(f"CalendarEvent created: {calendar_event.title} for user {calendar_event.user.username}")

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



@login_required
def schedule_mock_interview(request):
    try:
        # Debug: Log request type
        print(f"Request method: {request.method}, AJAX: {request.headers.get('X-Requested-With') == 'XMLHttpRequest'}")
        
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
                # Create appointment
                appointment = form.save(commit=False)
                appointment.application = JobApplication.objects.filter(user=request.user).first()  # Link to existing application
                
                # If no application exists, create a dummy one
                if not appointment.application:
                    first_job = Job.objects.first()
                    if first_job:
                        appointment.application = JobApplication.objects.create(user=request.user, job=first_job)
                        print(f"Created JobApplication for user {request.user.username} with job {first_job.title}")  # Debug
                    else:
                        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                            return JsonResponse({'success': False, 'error': 'No jobs available to create an application.'})
                        messages.error(request, "No jobs available to create an application.")
                        return redirect('profile')
                
                # Ensure application is set
                if not appointment.application:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({'success': False, 'error': 'Failed to create application.'})
                    messages.error(request, "Failed to create application.")
                    return redirect('profile')
                
                appointment.consultant = User.objects.filter(is_staff=True).first()  # Assign a consultant (improve with logic)
                appointment.appointment_type = 'INTERVIEW'
                appointment.is_mock_interview = True
                appointment.video_link = "https://zoom.us/j/example"  # Placeholder; integrate Zoom API
                appointment.save()

                # Decrement quota
                profile.increment_mock_interviews()

                # Create calendar event
                CalendarEvent.objects.create(
                    title=f"Mock Interview - {appointment.interview_type}",
                    user=request.user,
                    start_time=appointment.scheduled_at,
                    end_time=appointment.scheduled_at + timedelta(hours=1),
                    related_appointment=appointment
                )

                # In-app notification
                Notification.objects.create(
                    user=request.user,
                    message=f"Mock interview scheduled for {appointment.scheduled_at}. Video Link: {appointment.video_link}"
                )

                # Email notification
                send_mail(
                    subject="Mock Interview Scheduled",
                    message=f"Your mock interview is scheduled for {appointment.scheduled_at}. Video Link: {appointment.video_link}. Type: {appointment.interview_type}, Role: {appointment.target_role}",
                    from_email="noreply@yourapp.com",  # Update with your email
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
        print(f"Exception in schedule_mock_interview: {str(e)}")  # Debug: Log exception
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)  # Fallback for non-AJAX



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
    if request.method == 'POST':
        for progress in progresses:
            status = request.POST.get(f'status_{progress.id}')
            if status in ['NOT_STARTED', 'IN_PROGRESS', 'COMPLETED']:
                progress.status = status
                progress.save()

        if all(p.status == 'COMPLETED' for p in progresses):
            if enrollment.current_stage == 'ENROLLED':
                enrollment.current_stage = 'STARTED'
            elif enrollment.current_stage == 'STARTED':
                enrollment.current_stage = 'EXAMS'
            elif enrollment.current_stage == 'EXAMS':
                enrollment.current_stage = 'INTERVIEW'
            elif enrollment.current_stage == 'INTERVIEW':
                enrollment.current_stage = 'CERTIFIED'
                enrollment.status = 'COMPLETED'
                enrollment.completed_at = timezone.now()
                if enrollment.course.has_certificate:
                    Certificate.objects.get_or_create(enrollment=enrollment)
            enrollment.save()
        messages.success(request, "Progress updated.")
        return redirect('admin_user_progress', enrollment_id=enrollment_id)
    return render(request, 'admin/admin_user_progress.html', {'enrollment': enrollment, 'progresses': progresses})

@login_required
def training_dashboard(request):
    profile = request.user.profile
    enrollments = Enrollment.objects.filter(profile=request.user.profile)
    certificates = Certificate.objects.filter(enrollment__profile=request.user.profile, enrollment__status='COMPLETED')  # Fixed: Only for completed enrollments
    available_courses = Course.objects.filter(tier_required__in=['FREE'] if not profile.is_pro and not profile.is_proplus else ['FREE', 'PRO'] if profile.is_pro else ['FREE', 'PRO', 'PRO_PLUS'])
    return render(request, 'training_dashboard.html', {
        'enrollments': enrollments,
        'certificates': certificates,
        'available_courses': available_courses
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