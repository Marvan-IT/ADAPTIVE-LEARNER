"""
Pydantic v2 models for the Adaptive Learning Generation Engine.

Request → AnalyticsSummary → LearningProfile → GenerationProfile
       → AdaptiveLessonContent → AdaptiveLesson (response)
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Input ─────────────────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    """Raw behavioral signals collected by the frontend during a concept session."""

    student_id: str
    concept_id: str
    time_spent_sec: float = Field(ge=0, description="Actual seconds the student spent on the concept")
    expected_time_sec: float = Field(gt=0, description="Expected seconds for an average student")
    attempts: int = Field(ge=1, description="Total answer attempts (must be >= 1)")
    wrong_attempts: int = Field(ge=0, description="Number of incorrect attempts")
    hints_used: int = Field(ge=0, description="Number of hints the student requested")
    revisits: int = Field(ge=0, description="How many times the student revisited the concept")
    recent_dropoffs: int = Field(ge=0, description="Drop-offs from this concept in recent sessions")
    skip_rate: float = Field(ge=0.0, le=1.0, description="Fraction of content sections skipped")
    quiz_score: float = Field(ge=0.0, le=1.0, description="Normalised quiz score [0, 1]")
    last_7d_sessions: int = Field(ge=0, description="Number of learning sessions in the past 7 days")

    @model_validator(mode="after")
    def wrong_le_attempts(self) -> "AnalyticsSummary":
        """wrong_attempts must never exceed total attempts."""
        if self.wrong_attempts > self.attempts:
            raise ValueError("wrong_attempts cannot exceed attempts")
        return self


class AdaptiveLessonRequest(BaseModel):
    """Top-level API request body for POST /api/v3/adaptive/lesson."""

    student_id: uuid.UUID
    concept_id: str
    analytics_summary: AnalyticsSummary


# ── Intermediate — LearningProfile ────────────────────────────────────────────

class LearningProfile(BaseModel):
    """
    Deterministic classification of a student's current learning state.
    Produced by profile_builder.build_learning_profile().
    """

    speed: Literal["SLOW", "NORMAL", "FAST"]
    comprehension: Literal["STRUGGLING", "OK", "STRONG"]
    engagement: Literal["BORED", "ENGAGED", "OVERWHELMED"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    recommended_next_step: Literal["CONTINUE", "REMEDIATE_PREREQ", "ADD_PRACTICE", "CHALLENGE"]
    # Derived metric exposed for transparency / logging
    error_rate: float = Field(ge=0.0, le=1.0)


# ── Intermediate — GenerationProfile ──────────────────────────────────────────

class GenerationProfile(BaseModel):
    """
    LLM generation control parameters derived from LearningProfile.
    Produced by generation_profile.build_generation_profile().
    """

    explanation_depth: Literal["LOW", "MEDIUM", "HIGH"]
    reading_level: Literal["KID_SIMPLE", "SIMPLE", "STANDARD"]
    step_by_step: bool
    analogy_level: float = Field(ge=0.0, le=1.0)
    fun_level: float = Field(ge=0.0, le=1.0)
    card_count: int = Field(ge=1)
    practice_count: int = Field(ge=0)
    checkpoint_frequency: int = Field(ge=1)
    max_paragraph_lines: int = Field(ge=1)
    emoji_policy: Literal["NONE", "SPARING"]


# ── Output — lesson content ────────────────────────────────────────────────────

class AdaptiveLessonCard(BaseModel):
    """A single micro-card inside an adaptive lesson."""

    type: Literal["explain", "example", "mcq", "short_answer", "practice", "checkpoint"]
    title: str
    content: str = Field(description="Markdown-formatted card body")
    answer: str | None = None
    hints: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5)
    fun_element: str | None = None


class AdaptiveLessonContent(BaseModel):
    """The LLM-generated body of an adaptive lesson."""

    concept_explanation: str = Field(description="Markdown overview of the concept")
    cards: list[AdaptiveLessonCard]


# ── Output — remediation metadata ─────────────────────────────────────────────

class RemediationInfo(BaseModel):
    """Metadata about whether prerequisite remediation cards were injected."""

    included: bool
    prereq_concept_id: str | None = None
    prereq_title: str | None = None


# ── Top-level response ────────────────────────────────────────────────────────

class AdaptiveLesson(BaseModel):
    """
    Top-level API response for POST /api/v3/adaptive/lesson.
    Contains the full adaptive lesson plus all classification metadata.
    """

    student_id: str
    concept_id: str
    learning_profile: LearningProfile
    generation_profile: GenerationProfile
    lesson: AdaptiveLessonContent
    remediation: RemediationInfo
