import os
import openai
import httpx
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any
import json

# Load environment variables
load_dotenv()

# Set OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

class OpenAIService:
    def __init__(self):
        # Clear any proxy environment variables that might affect the client
        if 'HTTP_PROXY' in os.environ:
            del os.environ['HTTP_PROXY']
        if 'HTTPS_PROXY' in os.environ:
            del os.environ['HTTPS_PROXY']
        
        # Create a custom HTTP client without proxy settings
        http_client = httpx.Client(timeout=60.0)
        
        # Initialize OpenAI client with custom HTTP client
        api_key = os.getenv("OPENAI_API_KEY")
        self.client = openai.OpenAI(api_key=api_key, http_client=http_client)
    
    def generate_interview_questions(
        self,
        resume_content: Optional[str] = None,
        jd_content: Optional[str] = None,
        num_questions: int = 3,
        messages: Optional[List[Dict[str, str]]] = None
    ) -> List[str]:
        """Generate interview questions based on resume and/or JD content."""

        if messages:
            # Build context block from JD/resume if available and inject into last user message
            context_block = ""
            if jd_content:
                context_block += f"\n\nJOB DESCRIPTION:\n{jd_content}"
            if resume_content:
                context_block += f"\n\nRESUME:\n{resume_content}"

            chat_messages = messages.copy()
            if context_block:
                chat_messages[-1]["content"] = context_block + "\n\n" + chat_messages[-1]["content"]

            chat_messages[-1]["content"] += (
                f"\n\nRespond with valid JSON only, in this exact format:\n"
                f'{{ "questions": ["Question 1", "Question 2", ..., "Question {num_questions}"] }}\n'
                f"Generate exactly {num_questions} questions."
            )
        else:
            if jd_content and resume_content:
                user_content = (
                    f"A candidate has applied for a role. Use both the job description and the resume "
                    f"to generate exactly {num_questions} highly relevant interview questions that assess "
                    f"the candidate's fit for the role. Mix technical, role-specific, and behavioral questions.\n\n"
                    f"JOB DESCRIPTION:\n{jd_content}\n\nRESUME:\n{resume_content}"
                )
            elif jd_content:
                user_content = (
                    f"Generate exactly {num_questions} interview questions tailored to the following job description. "
                    f"Questions should test role-specific skills, technical knowledge, and behavioral fit.\n\n"
                    f"JOB DESCRIPTION:\n{jd_content}"
                )
            elif resume_content:
                user_content = (
                    f"Based on the following resume, generate exactly {num_questions} specific, "
                    f"relevant interview questions tailored to this candidate's skills and experience. "
                    f"Mix technical depth questions with behavioral ones.\n\nRESUME:\n{resume_content}"
                )
            else:
                user_content = (
                    f"Generate exactly {num_questions} professional technical interview questions "
                    f"to thoroughly assess a software engineering candidate. "
                    f"Include questions on problem-solving, system design, coding practices, and past experience."
                )

            user_content += (
                f"\n\nRespond with valid JSON only, in this exact format:\n"
                f'{{ "questions": ["Question 1", "Question 2", ..., "Question {num_questions}"] }}\n'
                f"Generate exactly {num_questions} questions."
            )

            chat_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an Axis Bank hiring manager running a 5-minute screening interview. "
                        "You ask SHORT, specific, conversational questions — one sentence each, "
                        "answerable in under 90 seconds. Never multi-part essays, never embedded "
                        "follow-ups, never more than 30 words per question. Sound like a real banker "
                        "on a call, not a written exam paper. Always respond with valid JSON only."
                    )
                },
                {"role": "user", "content": user_content}
            ]

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=chat_messages,
            temperature=0.4,
            max_tokens=2500,
            response_format={"type": "json_object"}
        )

        response_text = response.choices[0].message.content.strip()
        data = json.loads(response_text)
        questions = data.get("questions", [])

        return questions[:num_questions]
    
    def generate_text_to_speech(self, text: str, language: str = "en") -> bytes:
        """Generate text-to-speech audio for the given text.

        We use a SINGLE voice (``shimmer``) for every question regardless of
        language so the candidate hears one consistent interviewer across
        the welcome message, Q1, Q2, … Qn. ``shimmer`` is OpenAI's warmest
        female voice and is the clearest choice for Devanagari Hindi +
        Indian-English code-mixing (banking terms like CASA, KYC, HNI all
        sound natural). Previously we switched between ``nova`` (English)
        and ``alloy`` (Hindi) which caused the voice to shift mid-interview
        and ``alloy`` sounded robotic for Hindi.
        """
        if not hasattr(self, "_sarvam_tts"):
            from app.services.sarvam_service import SarvamService

            self._sarvam_tts = SarvamService()
        return self._sarvam_tts.generate_text_to_speech(text, language=language)
    
    def evaluate_interview(
        self,
        questions: List[Dict],
        resume_content: Optional[str] = None,
        jd_content: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """Evaluate the interview responses. Handles answers in Hindi or English."""

        # Prepare the conversation history if not provided
        if messages:
            chat_messages = messages.copy()
        else:
            # Build transcript
            conversation = []
            for q in questions:
                conversation.append(f"Question: {q['question']}")
                if q.get('answer'):
                    conversation.append(f"Answer: {q['answer']}")
                else:
                    conversation.append("Answer: [No answer provided]")

            conversation_text = "\n".join(conversation)

            # Build context block (JD + resume)
            context_parts = []
            if jd_content:
                context_parts.append(f"JOB DESCRIPTION:\n{jd_content}")
            if resume_content:
                context_parts.append(f"RESUME INFO:\n{resume_content}")
            context_block = "\n\n".join(context_parts)

            evaluation_instructions = """
                    Provide a comprehensive evaluation in JSON format with these exact keys:
                    "Overall assessment": "Text describing overall performance",
                    "Strengths identified": ["Strength 1", "Strength 2", "Strength 3"],
                    "Areas for improvement": ["Area 1", "Area 2", "Area 3"],
                    "Technical skills assessment": "Text assessing technical skills",
                    "Communication skills assessment": "Text assessing communication skills",
                    "Final recommendation": "Text with final recommendation"

                    Note that:
                    - 'Strengths identified' and 'Areas for improvement' MUST be arrays of strings
                    - 'Final recommendation' should ONLY recommend hiring if answers show genuine expertise
                    - If most answers are poor, vague, or nonsensical, explicitly recommend NOT hiring
                    - Answers may be in Hindi or English — evaluate the content and meaning regardless of language
                    - If an answer is in Hindi, translate and assess it accurately before scoring

                    Your response must be valid JSON enclosed in curly braces."""

            user_content = "Please analyze the following interview with extreme care and critical thinking.\n\n"
            if context_block:
                user_content += context_block + "\n\n"
            user_content += f"""INTERVIEW TRANSCRIPT:
                    {conversation_text}

                    For this evaluation, be particularly careful about:
                    1. Identifying vague, irrelevant, or nonsensical answers
                    2. Noting when a candidate is clearly trying to bluff or use generic statements
                    3. Being honest about poor performance - do not sugarcoat issues
                    4. Only giving positive feedback when genuinely deserved
                    5. Evaluating answers in Hindi or English on equal merit — assess meaning, not language choice
                    {f"6. Checking whether the candidate's skills match the requirements of the job description" if jd_content else ""}

                    {evaluation_instructions}"""

            chat_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a senior sales hiring expert with 15+ years of experience evaluating sales professionals "
                        "across B2B, SaaS, enterprise, and FMCG sectors. You assess candidates on sales methodology, "
                        "pipeline discipline, quota performance, negotiation skill, objection handling, and strategic thinking.\n\n"
                        "BE CRITICAL and HONEST. Immediately identify when a candidate gives vague, generic, or number-free answers "
                        "that lack the specificity expected of a strong sales professional.\n\n"
                        "IMPORTANT: Candidates may answer in Hindi or English. Evaluate the content and meaning of the answer "
                        "regardless of language — translate Hindi answers internally before scoring.\n\n"
                        "Your evaluations MUST meet these criteria:\n"
                        "1. Be brutally honest about sales skill deficiencies\n"
                        "2. Never recommend hiring someone whose answers lack real sales depth or data\n"
                        "3. Only identify genuine strengths that are clearly demonstrated with examples\n"
                        "4. Final recommendations must accurately reflect sales performance potential\n\n"
                        "You MUST provide VALID JSON output with specific fields."
                    )
                },
                {"role": "user", "content": user_content}
            ]
        
        try:
            # Call OpenAI API with increased temperature for more critical evaluation
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=chat_messages,
                temperature=0.5,
                max_tokens=1500
            )
            
            # Return the evaluation content
            return response.choices[0].message.content
        except Exception as e:
            import logging
            logging.error(f"Error in OpenAI evaluation: {str(e)}")
            # Return a simple error JSON if the API call fails
            return json.dumps({
                "Overall assessment": "Error in evaluation",
                "Strengths identified": ["Could not complete evaluation"],
                "Areas for improvement": ["Could not complete evaluation"],
                "Technical skills assessment": "Could not complete evaluation",
                "Communication skills assessment": "Could not complete evaluation",
                "Final recommendation": f"Please try again. Error: {str(e)}"
            })