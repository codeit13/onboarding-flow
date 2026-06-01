import json
import os
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional
from app.models.interview import InterviewSession, InterviewQuestion, ResumeData, JDData, FacialFeatures, InterviewData
from app.services.openai_service import OpenAIService
from app.services.deepgram_service import DeepgramService
from app.services.mcp_service import MCPService
from app.services.email_service import EmailService
from app.services.google_calendar_service import GoogleCalendarService
from dotenv import load_dotenv
from app.services.question_service import QuestionService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("interview-service")

# Load environment variables
load_dotenv()

# Bump when switching TTS provider/voice so old OpenAI MP3 caches are ignored.
TTS_CACHE_TAG = os.getenv("TTS_CACHE_TAG", "sarvam-bulbul-v3-aditya")


class InterviewService:
    def __init__(self):
        self.openai_service = OpenAIService()
        self.deepgram_service = DeepgramService()
        self.mcp_service = MCPService()
        self.question_service = QuestionService()
        self.email_service = EmailService()
        self.calendar_service = GoogleCalendarService()
        
        # Create data directories if they don't exist
        os.makedirs("interview_data", exist_ok=True)
        os.makedirs("mcp_data", exist_ok=True)
        os.makedirs("logs", exist_ok=True)

    @staticmethod
    def _tts_cache_tag_path(audio_dir: str) -> str:
        return os.path.join(audio_dir, ".tts_cache_tag")

    def is_audio_cache_current(self, audio_dir: str) -> bool:
        tag_path = self._tts_cache_tag_path(audio_dir)
        if not os.path.isfile(tag_path):
            return False
        try:
            with open(tag_path, encoding="utf-8") as f:
                return f.read().strip() == TTS_CACHE_TAG
        except OSError:
            return False

    def mark_audio_cache_current(self, audio_dir: str) -> None:
        os.makedirs(audio_dir, exist_ok=True)
        with open(self._tts_cache_tag_path(audio_dir), "w", encoding="utf-8") as f:
            f.write(TTS_CACHE_TAG)

    def load_or_generate_cached_audio(
        self, audio_dir: str, audio_path: str, text: str, language: str
    ) -> bytes:
        """Return MP3 bytes; regenerate when cache missing or from a prior TTS provider."""
        if os.path.exists(audio_path) and self.is_audio_cache_current(audio_dir):
            with open(audio_path, "rb") as f:
                return f.read()

        if os.path.exists(audio_path) and not self.is_audio_cache_current(audio_dir):
            logger.info(
                "Ignoring stale TTS cache at %s (tag mismatch); regenerating with Sarvam",
                audio_path,
            )

        audio_content = self.generate_speech(text, language=language)
        os.makedirs(audio_dir, exist_ok=True)
        with open(audio_path, "wb") as f:
            f.write(audio_content)
        self.mark_audio_cache_current(audio_dir)
        return audio_content

    def create_interview_session(
        self,
        resume_data: Optional[ResumeData] = None,
        jd_data: Optional[JDData] = None,
        name: str = "",
        email: Optional[str] = None,
        facial_features: Optional[FacialFeatures] = None,
        question_count: int = 3,
        language: str = "en",
    ) -> Dict:
        """Create a new interview session.

        ``language`` is an ISO-639-1 code: ``"en"`` (default) or ``"hi"`` for
        Hindi. The QuestionService writes language-aware prompts and the
        OpenAI TTS layer keys off the same field to pick a Hindi-capable
        voice when generating audio.
        """
        # Generate unique interview ID using timestamp
        interview_id = datetime.now().strftime("%Y%m%d%H%M%S")

        # Generate questions based on JD and/or resume
        questions = self.question_service.generate_questions(
            resume_data, jd_data, question_count, language=language
        )

        # Localised welcome message — same script in English and Hindi.
        if language == "hi":
            welcome_message = (
                "नमस्ते। मैं आपका AI साक्षात्कारकर्ता हूँ। मैं आपसे कुछ छोटे सवाल "
                "पूछूँगा। कृपया हर सवाल का जवाब स्पष्ट रूप से दीजिए।"
            )
        else:
            welcome_message = (
                "Welcome to your interview. I will ask you a series of short "
                "questions. Please answer each question clearly."
            )

        # Create interview data structure
        interview_data = {
            "id": interview_id,
            "resume_data": resume_data.dict() if resume_data else None,
            "jd_data": jd_data.dict() if jd_data else None,
            "name": name,
            "email": email,
            "language": language,
            "facial_features": facial_features.dict() if facial_features else None,
            "questions": questions,
            "current_question_index": 0,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "evaluation": None,
            "metadata": {
                "welcome_message": welcome_message,
                "welcome_audio_path": f"interview_data/{interview_id}_audio/welcome.mp3",
                "question_count": question_count,
                "language": language,
            }
        }
        
        # Save interview data to file
        self._save_interview_data(interview_id, interview_data)

        # Pre-generate ALL audio (welcome + every question) in one batch so
        # the TTS voice stays consistent across the entire interview.
        self._pregeneate_all_audio(interview_id, interview_data, language)

        return interview_data

    def _pregeneate_all_audio(
        self, interview_id: str, interview_data: Dict, language: str
    ) -> None:
        """Pre-generate welcome + all question audio in a single pass.

        Generating everything up-front eliminates the per-question TTS call
        that can produce subtle voice-quality shifts between questions
        (different text → different prosody → perceived voice change).
        """
        audio_dir = f"interview_data/{interview_id}_audio"
        os.makedirs(audio_dir, exist_ok=True)

        # Welcome audio
        welcome_msg = interview_data.get("metadata", {}).get(
            "welcome_message", "Welcome to your interview."
        )
        welcome_path = f"{audio_dir}/welcome.mp3"
        try:
            audio = self.generate_speech(welcome_msg, language=language)
            with open(welcome_path, "wb") as f:
                f.write(audio)
            logger.info("Pre-generated welcome audio for %s", interview_id)
        except Exception as e:
            logger.error("Failed to pre-generate welcome audio: %s", e)

        # Question audio — iterate every question
        for idx, q in enumerate(interview_data.get("questions", [])):
            cache_file = f"{audio_dir}/question_{idx}.mp3"
            try:
                audio = self.generate_speech(q["question"], language=language)
                with open(cache_file, "wb") as f:
                    f.write(audio)
                logger.info(
                    "Pre-generated audio for Q%d/%d in %s",
                    idx + 1,
                    len(interview_data["questions"]),
                    interview_id,
                )
            except Exception as e:
                logger.error("Failed to pre-generate Q%d audio: %s", idx + 1, e)

        if os.path.isfile(welcome_path) or any(
            os.path.isfile(os.path.join(audio_dir, f"question_{i}.mp3"))
            for i, _ in enumerate(interview_data.get("questions", []))
        ):
            self.mark_audio_cache_current(audio_dir)
    
    def get_interview(self, interview_id: str) -> Optional[Dict]:
        """Get interview session data"""
        try:
            with open(os.path.join("interview_data", f"{interview_id}.json"), "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        
    def _save_interview_data(self, interview_id: str, data: Dict):
        """Save interview data to file"""
        file_path = os.path.join("interview_data", f"{interview_id}.json")
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
    
    def get_current_question(self, interview_id: str) -> Optional[Dict]:
        """Get the current question for an interview session with audio cache for consistency"""
        
        interview = self.get_interview(interview_id)
        if not interview:
            logger.warning(f"Interview not found: {interview_id}")
            return None
        
        current_index = interview["current_question_index"]
        if current_index >= len(interview["questions"]):
            logger.info(f"All questions have been asked for interview: {interview_id}")
            return None  # All questions have been asked
        
        question_text = interview["questions"][current_index]["question"]
        
        # Check if we already have cached audio for this question to ensure consistency
        audio_cache_dir = f"interview_data/{interview_id}_audio"
        os.makedirs(audio_cache_dir, exist_ok=True)
        audio_cache_file = f"{audio_cache_dir}/question_{current_index}.mp3"
        
        # Generate and cache audio if missing or from a prior TTS provider
        if not (
            os.path.exists(audio_cache_file)
            and self.is_audio_cache_current(audio_cache_dir)
        ):
            logger.info(f"Generating audio for question {current_index+1} in interview {interview_id}")
            try:
                lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
                self.load_or_generate_cached_audio(
                    audio_cache_dir, audio_cache_file, question_text, lang
                )
                logger.info(f"Cached audio for question {current_index+1} in interview {interview_id}")
            except Exception as e:
                logger.error(f"Error generating audio for question {current_index+1}: {str(e)}")
        
        question_data = {
            "question": question_text,
            "index": current_index,
            "total": len(interview["questions"]),
            "audio_cache_path": audio_cache_file
        }
        
        logger.info(f"Getting question {current_index+1}/{len(interview['questions'])} for interview {interview_id}: {question_data['question']}")
        return question_data
    
    def save_answer(self, interview_id: str, answer: str) -> bool:
        """Save answer for current question"""
        interview_data = self.get_interview(interview_id)
        if not interview_data:
            return False
        
        current_index = interview_data["current_question_index"]
        if current_index >= len(interview_data["questions"]):
            return False
            
        interview_data["questions"][current_index]["answer"] = answer
        interview_data["current_question_index"] += 1
        
        # If this was the last question, set end time
        if interview_data["current_question_index"] >= len(interview_data["questions"]):
            interview_data["end_time"] = datetime.now().isoformat()
        
        self._save_interview_data(interview_id, interview_data)
        return True
    
    def transcribe_audio(self, base64_audio: str) -> Dict:
        """Transcribe audio using Deepgram"""
        try:
            if not base64_audio or not isinstance(base64_audio, str):
                return {"success": False, "error": "Invalid audio data format"}
                
            result = self.deepgram_service.transcribe_base64_audio(base64_audio)
            
            # Additional validation on the result
            if not isinstance(result, dict):
                return {"success": False, "error": "Unexpected response format from transcription service"}
                
            return result
            
        except Exception as e:
            return {"success": False, "error": f"Transcription error: {str(e)}"}
    
    def generate_speech(self, text: str, language: str = "en") -> bytes:
        """Generate speech from text using OpenAI."""
        return self.openai_service.generate_text_to_speech(text, language=language)
    
    def evaluate_interview(self, interview_id: str) -> Dict:
        """Evaluate the interview"""
        
        interview = self.get_interview(interview_id)
        if not interview:
            logger.warning(f"Interview not found for evaluation: {interview_id}")
            return {"success": False, "error": "Interview not found"}
        
        # Check if all questions have been answered
        if interview["current_question_index"] < len(interview["questions"]):
            logger.warning(f"Not all questions answered for interview {interview_id}")
            return {"success": False, "error": "Not all questions have been answered"}

        # Check if any questions were actually answered with content
        questions_answered = 0
        poor_quality_answers = 0
        generic_answers = ["hello", "hi", "ok", "yes", "no", "thanks", "thank you"]
        
        for question in interview["questions"]:
            answer = question.get("answer", "").strip().lower() if question.get("answer") else ""
            if answer:
                questions_answered += 1
                
                # Check for poor quality answers (too short or generic)
                words = answer.split()
                if len(words) < 5 or answer in generic_answers:
                    poor_quality_answers += 1
        
        # If no questions were answered, return a special message
        if questions_answered == 0:
            logger.warning(f"No questions were answered in interview {interview_id}")
            return {
                "success": True, 
                "evaluation": {
                    "Overall assessment": "The interview was not completed. No questions were answered.",
                    "Strengths identified": [],
                    "Areas for improvement": ["Completing the interview by answering the questions"],
                    "Technical skills assessment": "Unable to assess technical skills as no questions were answered.",
                    "Communication skills assessment": "Unable to assess communication skills as no questions were answered.",
                    "Final recommendation": "No recommendation can be made at this time. Please complete the interview by answering the questions."
                }
            }
        
        # If more than 50% of answers are poor quality, add a note for evaluation
        quality_warning = ""
        if poor_quality_answers / questions_answered > 0.5:
            quality_warning = "WARNING: More than half of the answers appear to be generic or of poor quality. This should be reflected in the evaluation."
            logger.warning(f"Poor quality answers detected in interview {interview_id}")

        # Continue with normal evaluation if questions were answered
        # Get the actual detection results from the interview session
        detection_results = interview.get("detection_results", {})
        
        # Transform detection results into our metrics format
        real_time_metrics = {
            "emotionalState": {
                "confidence": detection_results.get("emotion_confidence", 0) * 100,
                "primaryEmotion": detection_results.get("emotion", "neutral"),
                "emotionBreakdown": {}
            },
            "posture": {
                "confidence": detection_results.get("pose_confidence", 0) * 100,
                "status": detection_results.get("pose", "Unknown"),
                "issues": []  # Add logic to determine issues based on pose
            },
            "eyeTracking": {
                "confidence": detection_results.get("eye_confidence", 0) * 100,
                "gazeStability": detection_results.get("eye_confidence", 0) * 100,
                "suspiciousMovements": detection_results.get("direction_looking") != "at-system",
                "direction": detection_results.get("eye_direction", "Unknown")
            },
            "cheatingDetection": {
                "confidence": self._calculate_cheating_confidence(detection_results),
                "suspiciousActivities": [
                    f"Multiple people detected: {detection_results.get('people_count', 1)} people" if detection_results.get('people_count', 1) > 1 else None,
                    "Communication device detected" if detection_results.get('communication_device_present', False) else None,
                    "Not looking at system" if detection_results.get('direction_looking') != "at-system" else None
                ],
                "riskLevel": self._calculate_risk_level(detection_results)
            },
            "overallConfidenceScore": self._calculate_overall_confidence(detection_results)
        }

        # Process emotion breakdown data to ensure it's properly formatted for the frontend
        emotion_breakdown = detection_results.get("emotion_breakdown", {})
        if emotion_breakdown:
            # Convert values to the format expected by the frontend
            # The frontend expects numbers between 0-1, while our backend might store as percentages or decimals
            for emotion, value in emotion_breakdown.items():
                # Ensure the value is a number between 0 and 1 (convert from percentage if needed)
                if isinstance(value, (int, float)):
                    if value > 1:  # If value is stored as percentage (e.g., 60 instead of 0.6)
                        value = value / 100
                    real_time_metrics["emotionalState"]["emotionBreakdown"][emotion] = value
                else:
                    # Handle any non-numeric values
                    try:
                        real_time_metrics["emotionalState"]["emotionBreakdown"][emotion] = float(value)
                    except (ValueError, TypeError):
                        real_time_metrics["emotionalState"]["emotionBreakdown"][emotion] = 0
        else:
            # Set default values only if no emotion breakdown is available
            real_time_metrics["emotionalState"]["emotionBreakdown"] = {
                "neutral": 0.6,
                "happy": 0.2,
                "sad": 0.1,
                "angry": 0.05,
                "surprise": 0.05
        }

        # Clean up None values from suspicious activities
        real_time_metrics["cheatingDetection"]["suspiciousActivities"] = [
            activity for activity in real_time_metrics["cheatingDetection"]["suspiciousActivities"] 
            if activity is not None
        ]

        # Load the MCP chain for this interview
        mcp_file = f"mcp_data/{interview_id}.json"
        if os.path.exists(mcp_file):
            self.mcp_service.load_from_file(mcp_file)
        
        # Add evaluation request to MCP with quality warning if needed
        evaluation_prompt = """Please evaluate this interview and provide feedback on the candidate's performance.
            Format your response as valid JSON with the following structure:
            {
                "Overall assessment": "Text describing overall performance",
                "Strengths identified": ["Strength 1", "Strength 2", "Strength 3"],
                "Areas for improvement": ["Area 1", "Area 2", "Area 3"],
                "Technical skills assessment": "Text assessing technical skills",
                "Communication skills assessment": "Text assessing communication skills",
                "Final recommendation": "Final hiring recommendation"
            }
            Note that 'Strengths identified' and 'Areas for improvement' must be arrays of strings."""
        
        if quality_warning:
            evaluation_prompt += f"\n\nIMPORTANT: {quality_warning}"
        
        self.mcp_service.add_user_message(evaluation_prompt)
        
        # Get resume and JD info if available
        resume_info = None
        if interview.get("resume_data") and interview["resume_data"].get("filename"):
            resume_info = f"Resume filename: {interview['resume_data']['filename']}"

        jd_info = None
        if interview.get("jd_data") and interview["jd_data"].get("content"):
            jd_info = interview["jd_data"]["content"]

        try:
            logger.info(f"Generating evaluation for interview {interview_id}")
            # Generate evaluation using MCP context
            evaluation_text = self.openai_service.evaluate_interview(
                questions=interview["questions"],
                resume_content=resume_info,
                jd_content=jd_info,
                messages=self.mcp_service.to_openai_messages()
            )
            
            try:
                # Clean up the evaluation text to ensure it's valid JSON
                # First, try to find JSON content between curly braces if there's extra text
                import re
                json_match = re.search(r'\{.*\}', evaluation_text, re.DOTALL)
                if json_match:
                    clean_json_text = json_match.group(0)
                else:
                    clean_json_text = evaluation_text
                
                # Log the cleaned JSON for debugging
                logger.info(f"Cleaned JSON for interview {interview_id}: {clean_json_text}")
                
                # Parse the JSON
                evaluation_json = json.loads(clean_json_text)
                logger.info(f"Successfully generated evaluation for interview {interview_id}")
                
                # Ensure all required fields are present
                required_fields = [
                    "Overall assessment", 
                    "Strengths identified", 
                    "Areas for improvement",
                    "Technical skills assessment",
                    "Communication skills assessment",
                    "Final recommendation"
                ]
                
                for field in required_fields:
                    if field not in evaluation_json:
                        evaluation_json[field] = "Not provided" if field not in ["Strengths identified", "Areas for improvement"] else []
                
                # Ensure strengths and improvements are arrays
                if "Strengths identified" in evaluation_json and not isinstance(evaluation_json["Strengths identified"], list):
                    evaluation_json["Strengths identified"] = [evaluation_json["Strengths identified"]]
                
                if "Areas for improvement" in evaluation_json and not isinstance(evaluation_json["Areas for improvement"], list):
                    evaluation_json["Areas for improvement"] = [evaluation_json["Areas for improvement"]]
                
                # Add real-time analysis to evaluation
                evaluation_json["Real time analysis"] = real_time_metrics
                
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing evaluation JSON for interview {interview_id}: Evaluation: {evaluation_text}")
                logger.error(f"JSON error details: {str(e)}")
                
                # Create a fallback evaluation
                evaluation_json = {
                    "Overall assessment": "Error parsing evaluation",
                    "Strengths identified": ["The system encountered an error processing the evaluation"],
                    "Areas for improvement": ["Please try again"],
                    "Technical skills assessment": "Unable to assess due to processing error",
                    "Communication skills assessment": "Unable to assess due to processing error",
                    "Final recommendation": "Please try the evaluation again",
                    "Real time analysis": real_time_metrics
                }
            
            # Add evaluation to MCP
            self.mcp_service.add_assistant_message(f"Evaluation: {json.dumps(evaluation_json)}")
            
            # Save updated MCP state
            self.mcp_service.save_to_file(mcp_file)
            
            # Save evaluation to interview data
            interview["evaluation"] = evaluation_json
            self._save_interview_data(interview_id, interview)

            # Trigger selection email if candidate is selected
            self._maybe_send_selection_email(interview, evaluation_json)

            return {"success": True, "evaluation": evaluation_json}
            
        except Exception as e:
            logger.exception(f"Error in evaluate_interview for {interview_id}: {str(e)}")
            error_evaluation = {
                "Overall assessment": "System Error",
                "Strengths identified": ["The evaluation could not be completed"],
                "Areas for improvement": ["Please try again later"],
                "Technical skills assessment": "Evaluation failed",
                "Communication skills assessment": "Evaluation failed",
                "Final recommendation": f"Error: {str(e)}",
                "Real time analysis": real_time_metrics
            }
            return {"success": False, "error": str(e), "evaluation": error_evaluation}

    def schedule_meet(self, interview_id: str, slot_iso: str) -> Dict:
        """
        Called by the interviewer after they've agreed on a time slot with the candidate.
        Creates a Google Meet event and emails the link to the candidate.
        """
        interview = self.get_interview(interview_id)
        if not interview:
            return {"success": False, "error": "Interview not found"}

        candidate_email = interview.get("email")
        candidate_name = interview.get("name", "Candidate")

        if not candidate_email:
            return {"success": False, "error": "No candidate email on record for this interview"}

        try:
            from datetime import datetime as dt
            slot_dt = dt.fromisoformat(slot_iso)
            slot_display = slot_dt.strftime("%A, %d %B %Y at %I:%M %p")
        except ValueError:
            return {"success": False, "error": f"Invalid slot format: '{slot_iso}'. Use ISO 8601 e.g. 2026-04-08T10:00"}

        logger.info(f"Creating Google Meet for interview {interview_id} at {slot_iso}")
        meet_result = self.calendar_service.create_interview_event(
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            start_datetime=slot_dt,
        )

        if not meet_result.get("success"):
            return {"success": False, "error": meet_result.get("error", "Failed to create Google Meet event")}

        meet_link = meet_result["meet_link"]

        email_sent = self.email_service.send_meet_link_email(
            to_email=candidate_email,
            candidate_name=candidate_name,
            meet_link=meet_link,
            slot_display=slot_display,
        )

        return {
            "success": True,
            "meet_link": meet_link,
            "slot": slot_display,
            "email_sent": email_sent,
        }

    def _maybe_send_selection_email(self, interview: Dict, evaluation: Dict) -> None:
        """Send the selection email and enable slot booking on the results page."""
        candidate_email = interview.get("email")
        candidate_name = interview.get("name", "Candidate")

        if not candidate_email:
            logger.info("No candidate email on record — skipping selection email.")
            return

        # Determine if candidate is selected based on final recommendation text
        final_recommendation = evaluation.get("Final recommendation", "").lower()
        selected_keywords = ["select", "hire", "recommend", "proceed", "offer", "congratul", "advance"]
        reject_keywords = ["not recommend", "not hire", "reject", "do not hire", "not select", "not suitable", "not proceed"]

        is_selected = (
            any(kw in final_recommendation for kw in selected_keywords)
            and not any(kw in final_recommendation for kw in reject_keywords)
        )

        if not is_selected:
            logger.info(f"Candidate {candidate_name} not selected — no email sent.")
            return

        # Integrity is considered low when cheating risk is medium or high
        risk_level = (
            evaluation.get("Real time analysis", {})
            .get("cheatingDetection", {})
            .get("riskLevel", "low")
        )
        integrity_low = risk_level in ("medium", "high")

        logger.info(
            f"Sending selection email to {candidate_email} "
            f"(integrity_low={integrity_low}, risk={risk_level})"
        )
        email_sent = self.email_service.send_selection_email(
            to_email=candidate_email,
            candidate_name=candidate_name,
            integrity_low=integrity_low,
        )

        metadata = interview.setdefault("metadata", {})
        metadata["selected_for_next_round"] = True
        metadata["selection_email_sent"] = bool(email_sent)
        metadata["selection_email_sent_at"] = datetime.now().isoformat()
        metadata["slot_booking_available_at"] = datetime.now().isoformat()
        self._save_interview_data(interview["id"], interview)

    def _calculate_risk_level(self, detection_results: Dict) -> str:
        """Calculate risk level based on detection results"""
        risk_factors = 0
        
        # Count risk factors
        if detection_results.get('people_count', 1) > 1:
            risk_factors += 2  # Multiple people is a serious risk
        if detection_results.get('communication_device_present', False):
            risk_factors += 2  # Communication device is a serious risk
        if detection_results.get('direction_looking') != "at-system":
            risk_factors += 1  # Not looking at system is a minor risk
        # Only count low eye confidence if it's very low (below 0.1) to reduce false positives
        if detection_results.get('eye_confidence', 0) < 0.1:
            risk_factors += 1  # Very low eye tracking confidence is a minor risk
            
        # Determine risk level
        if risk_factors >= 3:
            return "high"
        elif risk_factors >= 2:  # Require at least 2 points for medium risk
            return "medium"
        return "low"
        
    def _calculate_cheating_confidence(self, detection_results: Dict) -> float:
        """Calculate confidence score for cheating detection"""
        # Base confidence level
        base_confidence = 80.0
        
        # Add confidence based on people count reliability
        if detection_results.get('pose_confidence', 0) > 0.6:
            base_confidence += 5.0  # Higher pose confidence means more reliable people count
            
        # Add confidence based on eye tracking reliability
        if detection_results.get('eye_confidence', 0) > 0.6:
            base_confidence += 5.0  # Higher eye confidence means more reliable direction detection
            
        # Cap confidence at 95%
        return min(base_confidence, 95.0)

    def _calculate_overall_confidence(self, detection_results: Dict) -> float:
        """Calculate overall confidence score based on detection results"""
        # Weighted average of different confidence scores
        weights = {
            'emotion_confidence': 0.3,
            'pose_confidence': 0.3,
            'eye_confidence': 0.4
        }
        
        total_score = 0
        total_weight = 0
        
        for metric, weight in weights.items():
            if metric in detection_results:
                total_score += detection_results[metric] * weight * 100
                total_weight += weight
                
        if total_weight == 0:
            return 0
            
        return total_score / total_weight 
