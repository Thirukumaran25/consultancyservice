from django.shortcuts import render,redirect,get_object_or_404
from django.contrib.auth import authenticate, login
from .forms import SignupForm,ProfileForm,JobApplicationForm,JobForm
from .models import ChatQuestionAnswer, CandidateChat,Job,Profile,Subscription,Course,JobApplication,Appointment,Interaction,SupportQuery,Notification
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from difflib import SequenceMatcher
from datetime import date, timedelta
from django.core.paginator import Paginator
from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import re
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.contrib import messages
from .gemini import ask_gemini




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


@csrf_exempt
@login_required
def chatbot_api(request):
    if request.method != 'POST':
        return JsonResponse({'reply': "Invalid request."})

    data = json.loads(request.body)
    user_question = data.get('message', '').strip()

    if not user_question:
        return JsonResponse({'reply': "Please enter a question."})

    profile, _ = Profile.objects.get_or_create(user=request.user)
    user_chat_count = CandidateChat.objects.filter(candidate=request.user).count()

    if not profile.is_pro and user_chat_count >= FREE_CHAT_LIMIT:
        return JsonResponse({
            'reply': "⚠️ You have reached your free limit of 10 questions. Please upgrade to Pro.",
            'upgrade_required': True
        })
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
        answer=answer
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
    faq = get_object_or_404(ChatQuestionAnswer, id=id)
    faq.delete()
    return JsonResponse({'success': True})


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
    if request.user.is_authenticated:
        has_applied = JobApplication.objects.filter(
            job=job,
            user=request.user
        ).exists()

    return render(request, 'job_detail.html', {
        'job': job,
        'has_applied': has_applied
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
    profile = Profile.objects.get(user=request.user)
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
            return redirect('applied_jobs')
    else:
        form = JobApplicationForm()

    return render(request, 'apply_job.html', {'job': job, 'form': form, 'application': application})



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
def upgrade_pro(request):
    profile = Profile.objects.get(user=request.user)

    if request.method == "POST":
        profile.is_pro = True
        profile.save()
        subscription, created = Subscription.objects.get_or_create(
            user=request.user,
            defaults={
                "plan_name": "Pro",
                "start_date": date.today(),
                "end_date": date.today() + timedelta(days=30),
                "active": True
            }
        )

        return redirect("profile")

    return render(request, "upgrade.html")


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

    if request.method == "POST":
        resume_text = request.POST.get("resume_text", "").lower().strip()

        if resume_text: 
            keywords = ["python", "django", "sql", "project", "experience", "skills"]

            matched_keywords = [k for k in keywords if k in resume_text]
            missing_keywords = [k for k in keywords if k not in resume_text]

            score = int((len(matched_keywords) / len(keywords)) * 100)

            suggestions = [
                "Add more measurable achievements (numbers, %)." if "experience" in missing_keywords else "",
                "Include relevant job keywords in your resume." if missing_keywords else "",
                "Mention projects with tools and technologies used." if "project" in missing_keywords else "",
                "Improve formatting for readability.",
                "Highlight certifications and training courses."
            ]
  
            suggestions = [s for s in suggestions if s]

    return render(request, "resume_ai.html", {
        "profile": profile,
        "suggestions": suggestions,
        "score": score,
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords
    })



@login_required
def subscription_dashboard(request):
    subscription, created = Subscription.objects.get_or_create(
        user=request.user,
        defaults={
            "plan_name": "Pro",
            "start_date": date.today(),
            "end_date": date.today() + timedelta(days=30),
            "active": True
        }
    )

    return render(request, "subscription.html", {"subscription": subscription})


@login_required
def courses(request):
    courses = Course.objects.all()
    return render(request, 'courses.html', {'courses': courses})



@login_required
def profile(request):
    profile, created = Profile.objects.get_or_create(user=request.user)


    fields = [profile.phone, profile.bio, profile.education, profile.location,
              profile.experience, profile.skills, profile.resume]
    filled = sum(1 for f in fields if f)
    completion = int((filled / len(fields)) * 100) 

    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {
        'form': form,
        'profile': profile,
        'completion': completion
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
    context = {
        'total_jobs': Job.objects.count(),
        'total_candidates': Profile.objects.count(),
        'total_applications': JobApplication.objects.count(),
        'pending_queries': SupportQuery.objects.filter(resolved=False).count(),
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

    return render(request, 'admin/candidates.html', {'profiles': profiles})



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



from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.shortcuts import render

@staff_member_required
def admin_queries(request):
    queries = SupportQuery.objects.all().order_by('-created_at')

    status_filter = request.GET.get('status', 'ALL')
    priority_filter = request.GET.get('priority', 'ALL')
    search_query = request.GET.get('search', '').strip()
    sort = request.GET.get('sort', 'NEWEST')

    # Status filter
    if status_filter == 'OPEN':
        queries = queries.filter(resolved=False)
    elif status_filter == 'RESOLVED':
        queries = queries.filter(resolved=True)

    # Priority filter
    if priority_filter != 'ALL':
        queries = queries.filter(priority=priority_filter)

    # Search filter
    if search_query:
        queries = queries.filter(
            Q(user__username__icontains=search_query) |
            Q(subject__icontains=search_query)
        )

    # Sorting
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
