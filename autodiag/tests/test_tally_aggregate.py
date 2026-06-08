from tally_aggregate import aggregate_submissions


def test_aggregate_submissions_scores_api_response_shape():
    form_config = {
        "form_id": "FORM1",
        "disqualification_options": ["disqualified"],
        "context_questions": {
            "situation": {"key": "sit", "options": {"employee": "salarie"}},
            "felt_constraint": {"key": "felt", "options": {"energy": "energie"}},
        },
        "scored_questions": [
            {"key": "q1", "front": "energie", "scores": {"yes": 4, "maybe": 2}},
            {"key": "q2", "front": "attention", "scores": {"yes": 4, "maybe": 2}},
            {"key": "q3", "front": "liens", "scores": {"yes": 4, "maybe": 2}},
            {"key": "q4", "front": "moyens", "scores": {"yes": 4, "maybe": 2}},
        ],
    }
    scoring_config = {
        "fronts": ["energie", "attention", "liens", "moyens"],
        "normalization": {},
        "internal_flags": {
            "rationalisateur": {
                "conditions": {"require": {"attention": {"min": 10}}, "any_of": []}
            }
        },
        "profile_rules": [
            {
                "priority": 1,
                "condition": {
                    "type": "weakest_front",
                    "tiebreak_priority": ["moyens", "energie", "attention", "liens"],
                },
                "front_to_profile": {
                    "energie": "energy_profile",
                    "attention": "attention_profile",
                    "liens": "links_profile",
                    "moyens": "means_profile",
                },
            }
        ],
        "profiles": {
            "energy_profile": {"front": "energie", "front_label": "Énergie"},
            "attention_profile": {"front": "attention", "front_label": "Attention"},
            "links_profile": {"front": "liens", "front_label": "Liens"},
            "means_profile": {"front": "moyens", "front_label": "Moyens"},
        },
    }
    submissions = [
        {
            "responses": [
                {"questionId": "question_q1", "answer": "yes"},
                {"questionId": "question_q2", "answer": "maybe"},
                {"questionId": "question_q3", "answer": "yes"},
                {"questionId": "question_q4", "answer": "maybe"},
                {"questionId": "question_sit", "answer": "employee"},
                {"questionId": "question_felt", "answer": "energy"},
            ]
        },
        {
            "responses": [
                {"questionId": "question_q1", "answer": "maybe"},
                {"questionId": "question_q2", "answer": "yes"},
                {"questionId": "question_q3", "answer": "maybe"},
                {"questionId": "question_q4", "answer": "yes"},
                {"questionId": "question_sit", "answer": "employee"},
                {"questionId": "question_felt", "answer": "energy"},
            ]
        },
        {"responses": [{"questionId": "question_q1", "answer": "disqualified"}]},
    ]

    aggregate = aggregate_submissions(
        submissions,
        form_config=form_config,
        scoring_config=scoring_config,
    )

    assert aggregate.submission_count == 2
    assert aggregate.skipped_count == 1
    assert aggregate.average_scores == {
        "energie": 3.0,
        "attention": 3.0,
        "liens": 3.0,
        "moyens": 3.0,
    }
    assert aggregate.felt_constraint_counts == {"energie": 2}
    assert aggregate.situation_counts == {"salarie": 2}


def test_aggregate_submissions_supports_question_aliases_from_metadata():
    form_config = {
        "form_id": "FORM1",
        "context_questions": {
            "situation": {"key": "sit", "options": {}},
            "felt_constraint": {"key": "felt", "options": {}},
        },
        "scored_questions": [
            {"key": "q1", "front": "energie", "scores": {"yes": 4}},
            {"key": "q2", "front": "attention", "scores": {}},
            {"key": "q3", "front": "liens", "scores": {}},
            {"key": "q4", "front": "moyens", "scores": {}},
        ],
    }
    scoring_config = {
        "fronts": ["energie", "attention", "liens", "moyens"],
        "normalization": {},
        "internal_flags": {"rationalisateur": {"conditions": {"require": {}, "any_of": []}}},
        "profile_rules": [
            {
                "priority": 1,
                "condition": {"type": "weakest_front", "tiebreak_priority": ["moyens"]},
                "front_to_profile": {"moyens": "means_profile"},
            }
        ],
        "profiles": {"means_profile": {"front": "moyens", "front_label": "Moyens"}},
    }

    aggregate = aggregate_submissions(
        [{"responses": [{"questionId": "uuid-q1", "answer": "yes"}]}],
        questions=[{"id": "question_q1", "fields": [{"uuid": "uuid-q1"}]}],
        form_config=form_config,
        scoring_config=scoring_config,
    )

    assert aggregate.average_scores["energie"] == 4.0
