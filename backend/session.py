"""Per-Connection Session-State. 1:1 Port aus dem JS STATE-Objekt + lastAgentMessage."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceSession:
    mode: str = "idle"                       # idle | free | awaiting_upload | cv_received | interview | wrapping | ended
    caller_email: str | None = None
    selected_job_id: str | None = None
    selected_job_data: dict[str, Any] | None = None  # gecachte Job-Details aus voice.arveum.ai
    company_info: dict[str, Any] | None = None       # gecachte /api/company Daten (Name, Tagline, Beschreibung)
    cv_base64: str | None = None
    questions: list[str] = field(default_factory=list)
    current_question_idx: int = 0
    current_answer_buffer: list[str] = field(default_factory=list)
    answers: list[dict[str, Any]] = field(default_factory=list)
    score: int | str | None = None
    highlights: list[str] = field(default_factory=list)
    muted: bool = False
    last_agent_message: str = ""

    # Config aus dem Browser empfangen
    openai_voice: str = "shimmer"
    realtime_model: str = "gpt-realtime"
    backend_llm_model: str = "claude-haiku-4-5"
    question_count: int = 8

    def reset_for_new_call(self):
        self.mode = "free"
        self.caller_email = None
        self.selected_job_id = None
        self.selected_job_data = None
        self.cv_base64 = None
        self.questions = []
        self.current_question_idx = 0
        self.current_answer_buffer = []
        self.answers = []
        self.score = None
        self.highlights = []
        self.muted = False
        self.last_agent_message = ""

    def to_dashboard_dict(self):
        """Was das Frontend für sein Recruiter-Dashboard braucht."""
        d = {
            "mode": self.mode,
            "callerEmail": self.caller_email,
            "selectedJobId": self.selected_job_id,
            "cvUploaded": bool(self.cv_base64),
            "score": self.score,
            "highlights": self.highlights,
            "currentQuestionIdx": self.current_question_idx,
            "totalQuestions": len(self.questions),
        }
        if self.selected_job_data:
            d["selectedJobTitle"] = self.selected_job_data.get("title")
            d["selectedJobLocation"] = self.selected_job_data.get("location")
        return d
