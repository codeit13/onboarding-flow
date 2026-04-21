from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime


class ResumeData(BaseModel):
    content: str
    filename: str


class JDData(BaseModel):
    content: str  # plain text of the job description
    filename: Optional[str] = None  # original filename if uploaded


class FacialFeatures(BaseModel):
    encoding: List[float]
    photo: str


class InterviewData(BaseModel):
    resume_data: Optional[ResumeData] = None
    jd_data: Optional[JDData] = None
    email: Optional[str] = None
    name: str
    facial_features: FacialFeatures
    questions: List[Dict]
    current_question_index: int = 0
    start_time: datetime
    end_time: Optional[datetime] = None
    evaluation: Optional[Dict] = None
    metadata: Optional[Dict] = None


class InterviewQuestion(BaseModel):
    id: int
    question: str
    answer: Optional[str] = None


class InterviewSession(BaseModel):
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S"))
    resume: Optional[ResumeData] = None
    questions: List[InterviewQuestion] = []
    current_question_index: int = 0
    start_time: datetime = Field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    evaluation: Optional[Dict] = None
    
    
class EvaluationRequest(BaseModel):
    interview_id: str 