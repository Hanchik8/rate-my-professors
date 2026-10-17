"""Fictional demo data so the site has something to show. Resets on every restart."""

SCHOOLS = [
    ("Lakeshore State University", "Chicago, IL"),
    ("Pinecrest College", "Burlington, VT"),
    ("Delmar Institute of Technology", "Austin, TX"),
]
PROFESSORS = [  # (school index, first, last, department, title)
    (0, "Maya", "Okafor", "Computer Science", "Associate Professor"),
    (0, "Daniel", "Reyes", "Mathematics", "Professor"),
    (0, "Priya", "Nair", "Biology", "Lecturer"),
    (1, "Tom", "Albrecht", "History", "Professor"),
    (1, "Hana", "Sato", "Psychology", "Assistant Professor"),
    (2, "Luis", "Ferreira", "Physics", "Professor"),
    (2, "Grace", "Whitfield", "Economics", "Lecturer"),
    (2, "Omar", "Haddad", "Computer Science", "Assistant Professor"),
]
REVIEWS = [  # (prof index, course, term, overall, difficulty, take again, grade, comment, tags)
    (0, "CS101", "Fall 2025", 5, 3, True, "A", "Explains recursion with real examples and posts slides before every lecture. Weekly quizzes keep you honest.", ["Amazing lectures", "Clear grading criteria"]),
    (0, "CS101", "Spring 2025", 4, 3, True, "B", "Fair exams and she actually answers email. Group project was the best part of the course.", ["Group projects", "Accessible outside class"]),
    (0, "CS240", "Fall 2024", 5, 4, True, "A", "Hard class but she makes it worth it. Office hours were packed for a reason.", ["Inspirational", "Gives good feedback"]),
    (1, "MATH210", "Fall 2025", 2, 5, False, "C", "Moves fast and the exams look nothing like the homework. Start studying early.", ["Tough grader", "Test heavy"]),
    (1, "MATH210", "Spring 2025", 3, 5, True, "B", "Brilliant but assumes you already know the material. Go to the recitations.", ["Test heavy"]),
    (2, "BIO110", "Fall 2025", 4, 2, True, "A", "Clear slides, honest grading, and optional extra credit every month.", ["Clear grading criteria", "Lots of homework"]),
    (3, "HIST101", "Spring 2025", 5, 2, True, "A", "Tells history like a story. Two papers, no final, very manageable.", ["Amazing lectures", "Gives good feedback"]),
    (3, "HIST320", "Fall 2024", 4, 3, True, "B", "Lots of reading but the discussions make it click. Participation counts.", ["Participation matters"]),
    (4, "PSY100", "Fall 2025", 3, 2, True, "B", "Fine lectures, but the quizzes are picky about wording. Easy grade overall.", ["Test heavy"]),
    (5, "PHYS201", "Spring 2025", 4, 4, True, "B", "Derives everything on the board. Tough but he curves generously.", ["Tough grader", "Amazing lectures"]),
    (5, "PHYS201", "Fall 2024", 5, 4, True, "A", "Best physics teacher I have had. Weekly problem sets are long but fair.", ["Inspirational", "Lots of homework"]),
    (6, "ECON101", "Fall 2025", 2, 3, False, "C", "Reads from slides and grading criteria were unclear. Midterm surprised everyone.", ["Test heavy"]),
    (7, "CS101", "Fall 2025", 4, 3, True, "A", "New to teaching but clearly prepared. Labs are well designed.", ["Clear grading criteria", "Group projects"]),
]


def seed(repo):
    schools = [repo.add_school(n, c) for n, c in SCHOOLS]
    profs = [repo.add_professor(schools[s].id, f, l, d, t) for s, f, l, d, t in PROFESSORS]
    for pi, course, term, overall, diff, wta, grade, comment, tags in REVIEWS:
        repo.add_review(profs[pi].id, {
            "course": course, "term": term, "overall": overall, "difficulty": diff,
            "would_take_again": wta, "grade": grade, "comment": comment, "tags": tags,
        })
