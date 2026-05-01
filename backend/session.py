"""Per-Connection Session-State. 1:1 Port aus dem JS STATE-Objekt + lastAgentMessage."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceSession:
    mode: str = "idle"                       # idle | free | awaiting_upload | cv_received | interview | wrapping | ended
    caller_email: str | None = None
    selected_job_id: str | None = None
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
        self.cv_base64 = None
        self.questions = []
        self.current_question_idx = 0
        self.current_answer_buffer = []
        self.answers = []
        self.score = None
        self.highlights = []
        self.muted = False
        self.last_agent_message = ""

    def to_dashboard_dict(self, data: dict | None = None):
        """Was das Frontend für sein Recruiter-Dashboard braucht.

        Wenn data übergeben wird, werden Job-Title + Location für die UI mitgeliefert."""
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
        if data and self.selected_job_id:
            job = next((j for j in data.get("jobs", []) if j["id"] == self.selected_job_id), None)
            if job:
                d["selectedJobTitle"] = job["title"]
                d["selectedJobLocation"] = job["location"]
        return d
