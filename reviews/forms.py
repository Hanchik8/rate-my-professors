from django import forms

from .repository import GRADES, TAGS

SCORES = [(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")]


class ReviewForm(forms.Form):
    course = forms.CharField(max_length=20, label="Course code", help_text="For example CS101")
    term = forms.CharField(max_length=20, required=False, label="Term taken", help_text="For example Fall 2025")
    overall = forms.TypedChoiceField(choices=SCORES, coerce=int, widget=forms.RadioSelect,
                                     label="Overall quality (5 is best)")
    difficulty = forms.TypedChoiceField(choices=SCORES, coerce=int, widget=forms.RadioSelect,
                                        label="Difficulty (5 is hardest)")
    would_take_again = forms.ChoiceField(choices=[("yes", "Yes"), ("no", "No")], widget=forms.RadioSelect,
                                         label="Would you take this professor again?")
    grade = forms.ChoiceField(choices=[("", "Prefer not to say")] + [(g, g) for g in GRADES],
                              required=False, label="Grade received")
    tags = forms.MultipleChoiceField(choices=[(t, t) for t in TAGS], required=False,
                                     widget=forms.CheckboxSelectMultiple, label="Tags",
                                     help_text="Pick up to 3")
    comment = forms.CharField(min_length=20, max_length=1000, widget=forms.Textarea(attrs={"rows": 6}),
                              label="Your review", help_text="At least 20 characters. Keep it about teaching and grading.")

    def clean_course(self):
        return "".join(self.cleaned_data["course"].split()).upper()

    def clean_tags(self):
        tags = self.cleaned_data["tags"]
        if len(tags) > 3:
            raise forms.ValidationError("Pick no more than 3 tags.")
        return tags

    def clean_would_take_again(self):
        return self.cleaned_data["would_take_again"] == "yes"
