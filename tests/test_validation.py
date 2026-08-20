from __future__ import annotations

from kingdom_tech_desk.services.validation import ValidationService

from conftest import complete_report


def codes(result):
    return {(issue.field, issue.code) for issue in result.errors}


def test_it_does_not_work_is_rejected():
    validator = ValidationService()
    report = complete_report(
        title="It does not work",
        steps="It does not work.",
        expected="It should work.",
        actual="It does not work.",
        category_detail="Broken.",
    )
    result = validator.validate(report)
    assert not result.valid
    assert any(issue.code in {"vague", "too_short", "not_reproducible"} for issue in result.errors)


def test_watch_video_plus_evidence_is_rejected():
    validator = ValidationService()
    report = complete_report(
        steps="Watch the video.",
        actual="Watch this video because the transfer is broken.",
        category_detail="Watch the video.",
        evidence_count=1,
    )
    result = validator.validate(report)
    assert not result.valid
    assert ("steps", "vague") in codes(result) or ("steps", "too_short") in codes(result)


def test_complete_report_without_evidence_is_accepted():
    result = ValidationService().validate(complete_report())
    assert result.valid, [issue.user_message for issue in result.errors]


def test_complete_report_with_evidence_metadata_is_accepted():
    result = ValidationService().validate(complete_report(evidence_count=1))
    assert result.valid


def test_expected_and_actual_identical_are_rejected():
    text = "The transfer should connect to The Kingdom and leave the Hub without showing an error."
    result = ValidationService().validate(complete_report(expected=text, actual=text))
    assert not result.valid
    assert ("actual", "same_as_expected") in codes(result)


def test_one_action_reproduction_is_rejected():
    result = ValidationService().validate(
        complete_report(
            steps=(
                "I selected The Kingdom transfer once and then included a long description about the menu, "
                "the nearby portal, the weather, and other context without performing another action."
            )
        )
    )
    assert not result.valid
    assert ("steps", "not_reproducible") in codes(result)


def test_two_valid_reproduction_steps_pass():
    result = ValidationService().validate(
        complete_report(
            steps=(
                "1. I joined The Hub from the server list and waited for spawn to load completely.\n"
                "2. I interacted with the transfer NPC and selected The Kingdom destination from the menu."
            )
        )
    )
    assert ("steps", "not_reproducible") not in codes(result)


def test_nothing_attempted_is_valid_by_itself():
    result = ValidationService().validate(
        complete_report(
            troubleshooting=["nothing_attempted"],
            additional_details="Nothing else attempted yet because the crash closes Minecraft immediately.",
        )
    )
    assert ("troubleshooting", "exclusive_conflict") not in codes(result)


def test_nothing_attempted_with_other_choices_is_rejected():
    result = ValidationService().validate(
        complete_report(troubleshooting=["nothing_attempted", "rejoined_server"])
    )
    assert not result.valid
    assert ("troubleshooting", "exclusive_conflict") in codes(result)


def test_unknown_version_requires_reason():
    result = ValidationService().validate(complete_report(client_version="unknown"))
    assert ("client_version", "unknown_without_reason") in codes(result)
    accepted = ValidationService().validate(
        complete_report(client_version="unknown - the game closes before the title screen appears")
    )
    assert ("client_version", "unknown_without_reason") not in codes(accepted)


def test_detailed_sentence_can_contain_generic_phrase():
    result = ValidationService().validate(
        complete_report(
            actual=(
                "The purchase button does not work after I select 32 stone: the menu closes, "
                "my balance decreases by 50, and no stone appears in my inventory."
            )
        )
    )
    assert ("actual", "vague") not in codes(result)


def test_copying_same_answer_across_fields_is_rejected():
    paragraph = (
        "I selected the destination and the loading screen closed after five seconds while "
        "showing Unable to connect to world and returning me to the server list."
    )
    result = ValidationService().validate(
        complete_report(actual=paragraph, category_detail=paragraph)
    )
    assert any(issue.code == "copied_field" for issue in result.errors)


def test_normalization_removes_urls_mentions_and_markdown_noise():
    normalized = ValidationService.normalize("**Hello** <@123456789012345678> https://example.com   WORLD!!!")
    assert normalized == "hello world!"

def test_two_numbered_actions_pass_even_with_unlisted_action_verbs():
    report = complete_report(
        steps=(
            "1. I grabbed the support compass from the first inventory slot after joining the Hub.\n"
            "2. I chose Area Management from the menu and the entire form vanished without saving."
        )
    )
    result = ValidationService().validate(report)
    assert not any(issue.code == "not_reproducible" for issue in result.errors)

