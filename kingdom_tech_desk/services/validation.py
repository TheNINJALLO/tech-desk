from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

from kingdom_tech_desk.constants import DEFAULT_VAGUE_PHRASES, FIELD_STAGES
from kingdom_tech_desk.models.core import DraftStage, ValidationIssue, ValidationResult

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<[@#][!&]?\d+>")
MARKDOWN_RE = re.compile(r"[`*_~>|]+")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['_-][A-Za-z0-9]+)*")
VERSION_RE = re.compile(r"(?<!\d)(?:\d{1,3}\.){1,3}\d{1,4}(?:[-+._a-zA-Z0-9]*)?(?!\d)")
STEP_PREFIX_RE = re.compile(r"^\s*(?:\d{1,2}[.)-]|[-*•])\s+", re.MULTILINE)
SENTENCE_SPLIT_RE = re.compile(r"(?:\n+|(?<=[.!?;])\s+)")

TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

ACTION_VERBS = {
    "clicked",
    "click",
    "opened",
    "open",
    "selected",
    "select",
    "pressed",
    "press",
    "joined",
    "join",
    "used",
    "use",
    "entered",
    "enter",
    "typed",
    "type",
    "placed",
    "place",
    "broke",
    "break",
    "moved",
    "move",
    "transferred",
    "transfer",
    "interacted",
    "interact",
    "equipped",
    "equip",
    "crafted",
    "craft",
    "purchased",
    "purchase",
    "bought",
    "buy",
    "sold",
    "sell",
    "restarted",
    "restart",
    "rejoined",
    "retried",
    "retry",
    "waited",
    "wait",
    "ran",
    "run",
    "walked",
    "walk",
    "teleported",
    "teleport",
}


class ValidationService:
    def __init__(
        self,
        vague_phrases: Iterable[str] | None = None,
        minimum_combined_words: int = 45,
    ) -> None:
        self.vague_phrases = sorted(
            {self.normalize(phrase) for phrase in (vague_phrases or DEFAULT_VAGUE_PHRASES) if phrase},
            key=len,
            reverse=True,
        )
        self.minimum_combined_words = minimum_combined_words

    @staticmethod
    def normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = URL_RE.sub(" ", text)
        text = MENTION_RE.sub(" ", text)
        text = MARKDOWN_RE.sub(" ", text)
        text = re.sub(r"([!?.,])\1{2,}", r"\1", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip().lower()

    @classmethod
    def words(cls, value: Any) -> list[str]:
        return [match.group(0).lower() for match in WORD_RE.finditer(cls.normalize(value))]

    @classmethod
    def meaningful_characters(cls, value: Any) -> int:
        return sum(1 for character in cls.normalize(value) if character.isalnum())

    def _issue(
        self,
        field: str,
        code: str,
        user_message: str,
        staff_message: str | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            field=field,
            code=code,
            user_message=user_message,
            staff_message=staff_message or user_message,
            remediation_stage=FIELD_STAGES.get(field, DraftStage.CONTEXT),
        )

    def _vague_dominated(self, field: str, value: Any) -> bool:
        normalized = self.normalize(value)
        if not normalized:
            return True
        if field == "additional_details" and normalized in {
            "nothing else attempted yet",
            "no additional troubleshooting yet",
            "nothing else yet",
        }:
            return False
        if normalized in self.vague_phrases:
            return True
        remainder = normalized
        matched = False
        for phrase in self.vague_phrases:
            if phrase and phrase in remainder:
                matched = True
                remainder = remainder.replace(phrase, " ")
        remainder_words = [word for word in self.words(remainder) if word not in TITLE_STOPWORDS]
        all_words = self.words(normalized)
        return matched and len(remainder_words) < 4 and len(all_words) < 10

    @classmethod
    def _near_duplicate(cls, left: Any, right: Any) -> bool:
        left_normalized = cls.normalize(left)
        right_normalized = cls.normalize(right)
        if not left_normalized or not right_normalized:
            return False
        if left_normalized == right_normalized:
            return True
        if min(len(left_normalized), len(right_normalized)) < 12:
            return False
        ratio = SequenceMatcher(None, left_normalized, right_normalized).ratio()
        left_tokens = set(cls.words(left_normalized))
        right_tokens = set(cls.words(right_normalized))
        union = left_tokens | right_tokens
        jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
        return ratio >= 0.86 or (jaccard >= 0.84 and min(len(left_tokens), len(right_tokens)) >= 5)

    @classmethod
    def count_distinct_actions(cls, value: Any) -> int:
        normalized = unicodedata.normalize("NFKC", str(value or ""))
        candidates: list[tuple[str, bool]] = []
        for line in normalized.splitlines():
            starts_numbered = bool(STEP_PREFIX_RE.match(line))
            cleaned = STEP_PREFIX_RE.sub("", line).strip()
            if cleaned and len(cls.words(cleaned)) >= 3:
                candidates.append((cleaned, starts_numbered))

        if len(candidates) < 2:
            candidates = [
                (segment.strip(), bool(STEP_PREFIX_RE.match(segment)))
                for segment in SENTENCE_SPLIT_RE.split(normalized)
                if segment.strip()
            ]

        distinct: list[str] = []
        for candidate, starts_numbered in candidates:
            tokens = cls.words(candidate)
            if len(tokens) < 3:
                continue
            has_action = bool(set(tokens) & ACTION_VERBS)
            if not has_action and not starts_numbered and len(candidates) <= 2:
                continue
            normalized_candidate = " ".join(tokens)
            if not any(cls._near_duplicate(normalized_candidate, existing) for existing in distinct):
                distinct.append(normalized_candidate)
        return len(distinct)

    def validate(self, data: dict[str, Any]) -> ValidationResult:
        normalized_fields: dict[str, Any] = {}
        for key, value in data.items():
            normalized_fields[key] = (
                [self.normalize(item) for item in value] if isinstance(value, list) else self.normalize(value)
            )

        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        required_text = {
            "category": "Select the issue category.",
            "platform": "Select the device or platform.",
            "affected_scope": "Select who is affected.",
            "gamertag": "Enter your Minecraft gamertag.",
            "where_when": "Include where the issue happened and approximately when.",
            "title": "Enter a useful issue title.",
            "steps": "List the exact actions that led to the issue.",
            "expected": "Explain what should have happened.",
            "actual": "Explain what actually happened.",
            "category_detail": "Complete the category-specific technical detail.",
            "frequency": "Select how often the problem occurs.",
            "client_version": "Enter the Minecraft client version.",
            "additional_details": "State what else you tried, or say that nothing else was attempted.",
        }
        for field, message in required_text.items():
            if not normalized_fields.get(field):
                errors.append(self._issue(field, "required", message))

        gamertag = str(data.get("gamertag", "")).strip()
        if gamertag and not 3 <= len(gamertag) <= 32:
            errors.append(
                self._issue("gamertag", "length", "Gamertag must contain between 3 and 32 characters.")
            )

        if self.meaningful_characters(data.get("where_when")) < 15:
            errors.append(
                self._issue(
                    "where_when",
                    "too_short",
                    "Add the server or world, general area, and an approximate time. Coordinates help when available.",
                )
            )

        title_words = [word for word in self.words(data.get("title")) if word not in TITLE_STOPWORDS]
        if self.meaningful_characters(data.get("title")) < 12 or len(title_words) < 3:
            errors.append(
                self._issue(
                    "title",
                    "not_descriptive",
                    "Use at least three meaningful words, such as ‘Land claim menu closes’. ",
                )
            )

        if self.meaningful_characters(data.get("steps")) < 60:
            errors.append(
                self._issue(
                    "steps",
                    "too_short",
                    "Provide at least 60 characters describing the exact actions in order.",
                )
            )
        action_count = self.count_distinct_actions(data.get("steps"))
        if action_count < 2:
            errors.append(
                self._issue(
                    "steps",
                    "not_reproducible",
                    "List at least two distinct actions in the order you performed them.",
                    f"Detected {action_count} distinct action(s).",
                )
            )

        if self.meaningful_characters(data.get("expected")) < 15:
            errors.append(
                self._issue(
                    "expected",
                    "too_short",
                    "Explain the result that should have appeared after the final step.",
                )
            )

        if self.meaningful_characters(data.get("actual")) < 35:
            errors.append(
                self._issue(
                    "actual",
                    "too_short",
                    "Describe what appeared, changed, stopped, closed, disappeared, or failed.",
                )
            )

        if self._near_duplicate(data.get("expected"), data.get("actual")):
            errors.append(
                self._issue(
                    "actual",
                    "same_as_expected",
                    "Expected and actual results must describe two different outcomes.",
                )
            )

        if self.meaningful_characters(data.get("category_detail")) < 20:
            errors.append(
                self._issue(
                    "category_detail",
                    "too_short",
                    "Add the requested category-specific names, messages, amounts, locations, or identifiers.",
                )
            )

        troubleshooting = data.get("troubleshooting", [])
        if not isinstance(troubleshooting, list) or not troubleshooting:
            errors.append(
                self._issue(
                    "troubleshooting",
                    "required",
                    "Select at least one troubleshooting option, including ‘Nothing attempted yet’ when accurate.",
                )
            )
        elif "nothing_attempted" in troubleshooting and len(troubleshooting) > 1:
            errors.append(
                self._issue(
                    "troubleshooting",
                    "exclusive_conflict",
                    "‘Nothing attempted yet’ cannot be selected with other troubleshooting actions.",
                )
            )

        version = self.normalize(data.get("client_version"))
        if version:
            if version.startswith("unknown"):
                reason = version.removeprefix("unknown").lstrip(" :-")
                if self.meaningful_characters(reason) < 10:
                    errors.append(
                        self._issue(
                            "client_version",
                            "unknown_without_reason",
                            "When the version is unknown, include why it cannot be checked.",
                        )
                    )
            elif not VERSION_RE.search(version):
                errors.append(
                    self._issue(
                        "client_version",
                        "invalid_format",
                        "Enter the numeric version shown on Minecraft’s title screen, such as 26.44 or 1.26.44.",
                    )
                )

        for field in ("title", "steps", "expected", "actual", "category_detail"):
            if data.get(field) and self._vague_dominated(field, data[field]):
                errors.append(
                    self._issue(
                        field,
                        "vague",
                        "This answer is too vague. Name the action and describe the visible result instead of only saying it failed.",
                    )
                )

        if data.get("additional_details") and self._vague_dominated(
            "additional_details", data["additional_details"]
        ):
            errors.append(
                self._issue(
                    "additional_details",
                    "vague",
                    "State what else you tried, or write ‘Nothing else attempted yet’. ",
                )
            )

        duplicate_fields = ["steps", "expected", "actual", "category_detail", "additional_details"]
        for index, left_name in enumerate(duplicate_fields):
            left = data.get(left_name)
            if not left or len(self.words(left)) < 6:
                continue
            for right_name in duplicate_fields[index + 1 :]:
                right = data.get(right_name)
                if not right or len(self.words(right)) < 6:
                    continue
                if self._near_duplicate(left, right):
                    errors.append(
                        self._issue(
                            right_name,
                            "copied_field",
                            f"The {right_name.replace('_', ' ')} answer appears copied from another field. Give the specific information requested there.",
                        )
                    )
                    break

        combined_fields = (
            "where_when",
            "title",
            "steps",
            "expected",
            "actual",
            "category_detail",
            "additional_details",
        )
        combined_words = sum(len(self.words(data.get(field))) for field in combined_fields)
        if combined_words < self.minimum_combined_words:
            errors.append(
                self._issue(
                    "steps",
                    "combined_detail",
                    f"The written report contains {combined_words} meaningful words. Add enough detail to reach at least {self.minimum_combined_words}.",
                    f"Combined meaningful word count: {combined_words}.",
                )
            )

        if action_count >= 4 and combined_words >= 80:
            warnings.append(
                self._issue(
                    "steps",
                    "strong_reproduction",
                    "The reproduction steps are detailed and should help staff test the issue quickly.",
                )
            )

        # Remove duplicate errors generated by overlapping checks while preserving order.
        unique_errors: list[ValidationIssue] = []
        seen: set[tuple[str, str]] = set()
        for issue in errors:
            key = (issue.field, issue.code)
            if key not in seen:
                seen.add(key)
                unique_errors.append(issue)

        failed_stage = min((issue.remediation_stage for issue in unique_errors), default=None)
        score = max(0, min(100, 100 - len(unique_errors) * 11 + len(warnings) * 2))
        return ValidationResult(
            valid=not unique_errors,
            errors=unique_errors,
            warnings=warnings,
            score=score,
            normalized_fields=normalized_fields,
            failed_stage=failed_stage,
        )
