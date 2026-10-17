from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import ReviewForm
from .store import repo


def home(request):
    q = request.GET.get("q", "")
    school = request.GET.get("school", "")
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "schools": repo.schools(), "results": repo.search(q, school),
    })


def _professor_or_404(slug):
    prof = repo.professor(slug)
    if prof is None:
        raise Http404("Professor not found")
    return prof


def professor_detail(request, slug):
    prof = _professor_or_404(slug)
    sort = "helpful" if request.GET.get("sort") == "helpful" else "newest"
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": repo.stats(prof.id),
        "reviews": repo.reviews_for(prof.id, sort), "sort": sort,
    })


def review_new(request, slug):
    prof = _professor_or_404(slug)
    form = ReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        repo.add_review(prof.id, form.cleaned_data)
        return redirect("professor", slug=prof.slug)
    return render(request, "reviews/review_form.html", {"prof": prof, "form": form})


@require_POST
def review_vote(request, review_id):
    review = repo.review(review_id)
    if review is None:
        raise Http404("Review not found")
    repo.vote(review_id, helpful=request.POST.get("vote") == "up")
    prof = repo.professor_by_id(review.professor_id)
    return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
