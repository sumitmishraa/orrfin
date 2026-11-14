"""Intake form fields and answers (BUILD_PLAN §5 form_fields). Pure: no database."""

from app.modules.intake_forms.fields import clean_values, field_problems

FORM = [
    {"key": "seats", "label": "Seats", "kind": "number", "required": True, "options": []},
    {"key": "annual_cost", "label": "Annual cost", "kind": "money", "required": False, "options": []},
    {"key": "renewal", "label": "Renewal date", "kind": "date", "required": False, "options": []},
    {"key": "data_class", "label": "Data handled", "kind": "choice", "required": True,
     "options": ["Public", "Personal data"]},
    {"key": "notes", "label": "Notes", "kind": "text", "required": False, "options": []},
    {"key": "owner", "label": "Owner", "kind": "user", "required": False, "options": []},
]


def test_a_well_formed_form_has_no_problems():
    assert field_problems(FORM) == []


def test_a_form_that_cannot_be_saved_says_why():
    problems = field_problems([
        {"key": "Seats", "label": "Seats", "kind": "number"},                       # upper-case key
        {"key": "cost", "label": "", "kind": "money"},                              # no label
        {"key": "cost", "label": "Cost again", "kind": "money"},                    # key used twice
        {"key": "script", "label": "Script", "kind": "formula"},                    # a kind that does not exist
        {"key": "tier", "label": "Tier", "kind": "choice", "options": []},          # a choice with nothing to choose
        {"key": "dupes", "label": "Dupes", "kind": "choice", "options": ["A", "A"]},
        {"key": "note", "label": "Note", "kind": "text", "options": ["A"]},         # options on a text question
    ])
    assert len(problems) == 7
    assert len(field_problems([{"key": f"q{i}", "label": "Q", "kind": "text"} for i in range(41)])) == 1


def test_good_answers_are_stored_as_clean_text():
    clean, problems = clean_values(FORM, {
        "seats": " 25 ", "annual_cost": "120000.5", "renewal": "2027-03-31", "data_class": "Personal data",
        "notes": "", "owner": "6F9619FF-8B86-D011-B42D-00C04FC964FF"})
    assert problems == []
    assert clean == {"seats": "25", "annual_cost": "120000.50", "renewal": "2027-03-31",
                     "data_class": "Personal data", "owner": "6f9619ff-8b86-d011-b42d-00c04fc964ff"}


def test_bad_answers_are_all_named_and_nothing_is_guessed():
    clean, problems = clean_values(FORM, {
        "annual_cost": "1,20,000", "renewal": "31/03/2027", "data_class": "Secret", "owner": "me",
        "notes": "x" * 2001, "hidden_field": "1"})
    assert clean == {}
    assert len(problems) == 7  # the five bad answers, the unknown key, and the missing required "seats"


def test_an_answer_sent_as_a_number_is_refused():
    clean, problems = clean_values(FORM, {"seats": 25, "data_class": "Public", "annual_cost": 120000.5})
    assert clean == {"data_class": "Public"}
    assert problems == ["Seats: send the answer as text.", "Annual cost: send the answer as text."]


def test_money_answers_cannot_be_negative_or_scientific():
    for bad in ("-5.00", "1e5", "12.345", "₹500"):
        _, problems = clean_values(FORM, {"seats": "1", "data_class": "Public", "annual_cost": bad})
        assert problems, bad
