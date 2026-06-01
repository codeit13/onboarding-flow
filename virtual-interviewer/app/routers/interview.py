from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body, BackgroundTasks, Query
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
from typing import Optional, Dict, List, Any
import io
import json
import base64
import face_recognition
import numpy as np
from app.models.interview import ResumeData, JDData, FacialFeatures, InterviewData
from app.services.interview_service import InterviewService
import os
import logging

logger = logging.getLogger("interview-router")

router = APIRouter(prefix="/api/interview", tags=["interview"])
interview_service = InterviewService()


@router.get("/google-auth/status")
async def google_auth_status():
    """Return whether Google Calendar OAuth has been connected."""
    return JSONResponse(content={
        "success": True,
        "status": interview_service.calendar_service.get_status(),
    })


@router.get("/google-auth/connect")
async def google_auth_connect(return_url: Optional[str] = Query(None)):
    """Redirect the user to Google's OAuth consent flow."""
    try:
        auth_url = interview_service.calendar_service.get_authorization_url(return_url=return_url)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting Google OAuth flow: {str(e)}")


@router.get("/google-auth/callback")
async def google_auth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Exchange the Google OAuth code and redirect back to the UI."""
    calendar_service = interview_service.calendar_service

    if error:
        redirect_url = calendar_service.get_callback_redirect(state, error=error)
        return RedirectResponse(url=redirect_url)

    if not code:
        redirect_url = calendar_service.get_callback_redirect(state, error="missing_code")
        return RedirectResponse(url=redirect_url)

    try:
        calendar_service.exchange_code(code, state=state)
        logger.info("Google OAuth callback completed successfully")
        redirect_url = calendar_service.get_callback_redirect(state)
        return RedirectResponse(url=redirect_url)
    except Exception as e:
        logger.error(f"Google OAuth callback failed: {str(e)}")
        redirect_url = calendar_service.get_callback_redirect(state, error=str(e))
        return RedirectResponse(url=redirect_url)

@router.post("/start")
async def start_interview(
    resume_file: Optional[UploadFile] = File(None),
    jd_file: Optional[UploadFile] = File(None),
    jd_text: Optional[str] = Form(None),
    name: str = Form(...),
    email: Optional[str] = Form(None),
    photo: str = Form(...),
    question_count: int = Form(3),
    language: str = Form("en"),
):
    """Start a new interview session.

    JD can be supplied as a .txt/.docx file upload (jd_file) OR as plain
    copy-pasted text (jd_text).  Resume upload remains optional.
    """

    try:
        # Validate question count
        if question_count < 3 or question_count > 8:
            raise HTTPException(status_code=400, detail="Question count must be between 3 and 8")

        # ── Resume ──────────────────────────────────────────────────────────
        resume_data = None
        if resume_file:
            content = await resume_file.read()
            content_base64 = base64.b64encode(content).decode('ascii')
            resume_data = ResumeData(
                content=content_base64,
                filename=resume_file.filename
            )

        # ── Job Description ─────────────────────────────────────────────────
        jd_data = None
        if jd_file:
            jd_content_bytes = await jd_file.read()
            filename = jd_file.filename or ""
            if filename.lower().endswith(".docx"):
                try:
                    import docx
                    from io import BytesIO
                    doc = docx.Document(BytesIO(jd_content_bytes))
                    jd_text_extracted = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
                except Exception as docx_err:
                    raise HTTPException(status_code=400, detail=f"Error reading .docx JD file: {str(docx_err)}")
            else:
                # .txt or any other plain-text file
                jd_text_extracted = jd_content_bytes.decode("utf-8", errors="replace")
            jd_data = JDData(content=jd_text_extracted, filename=filename)
        elif jd_text and jd_text.strip():
            jd_data = JDData(content=jd_text.strip())

        # ── Face processing ─────────────────────────────────────────────────
        try:
            photo_data = base64.b64decode(photo.split(',')[1])
            photo_np = np.frombuffer(photo_data, np.uint8)
            image = face_recognition.load_image_file(io.BytesIO(photo_np))

            face_locations = face_recognition.face_locations(image)
            if not face_locations:
                raise HTTPException(status_code=400, detail="No face detected in the photo")

            face_encoding = face_recognition.face_encodings(image, face_locations)[0]
            facial_features = FacialFeatures(
                encoding=face_encoding.tolist(),
                photo=photo
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error processing face: {str(e)}")

        # Normalise language code — accept "en", "english", "hi", "hindi"
        lang_norm = (language or "en").strip().lower()
        if lang_norm in ("hi", "hindi", "हिंदी", "हिन्दी"):
            lang_norm = "hi"
        else:
            lang_norm = "en"

        # ── Create session ───────────────────────────────────────────────────
        interview_session = interview_service.create_interview_session(
            resume_data=resume_data,
            jd_data=jd_data,
            name=name,
            email=email,
            facial_features=facial_features,
            question_count=question_count,
            language=lang_norm,
        )

        welcome_message = "Welcome to your interview. I will ask you a series of questions. Please answer each question clearly."
        if "metadata" in interview_session and "welcome_message" in interview_session["metadata"]:
            welcome_message = interview_session["metadata"]["welcome_message"]

        return JSONResponse(content={
            "success": True,
            "interview_id": interview_session["id"],
            "message": "Interview session created successfully",
            "welcome_message": welcome_message
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating interview: {str(e)}")

@router.post("/{interview_id}/verify_face")
async def verify_face(interview_id: str, data: Dict[str, Any] = Body(...)):
    """Verify if the face in the photo matches the one from interview start"""
    try:
        if "photo" not in data:
            raise HTTPException(status_code=400, detail="Photo data is required")
            
        photo = data["photo"]
        
        # Get stored facial features
        interview = interview_service.get_interview(interview_id)
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        stored_encoding = np.array(interview["facial_features"]["encoding"])
        
        # Process new photo
        try:
            # Extract base64 data after the data URL prefix
            if ',' in photo:
                photo_data = base64.b64decode(photo.split(',')[1])
            else:
                photo_data = base64.b64decode(photo)
                
            photo_np = np.frombuffer(photo_data, np.uint8)
            image = face_recognition.load_image_file(io.BytesIO(photo_np))
        except Exception as e:
            return JSONResponse(content={
                "success": False,
                "match": False,
                "message": f"Error processing photo: {str(e)}"
            })
        
        # Get facial features from new photo
        face_locations = face_recognition.face_locations(image)
        if not face_locations:
            return JSONResponse(content={
                "success": True,
                "match": False,
                "message": "No face detected in the current frame"
            })
        
        face_encoding = face_recognition.face_encodings(image, face_locations)[0]
        
        # Compare faces
        match = face_recognition.compare_faces([stored_encoding], face_encoding, tolerance=0.6)[0]
        
        return JSONResponse(content={
            "success": True,
            "match": bool(match),
            "name": interview["name"] if match else None
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error verifying face: {str(e)}")

@router.get("/{interview_id}")
async def get_interview(interview_id: str):
    """Get interview session details"""
    
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    return JSONResponse(content={
        "success": True,
        "interview": interview
    })

@router.get("/{interview_id}/question")
async def get_current_question(interview_id: str):
    """Get the current question for an interview session"""
    
    question = interview_service.get_current_question(interview_id)
    if not question:
        return JSONResponse(content={
            "success": False,
            "message": "No more questions or interview not found"
        })
    
    # Remove internal audio cache path from response
    if "audio_cache_path" in question:
        question.pop("audio_cache_path")
    
    return JSONResponse(content={
        "success": True,
        "question": question
    })

@router.post("/{interview_id}/answer")
async def save_answer(interview_id: str, answer: str = Body(..., embed=True)):
    """Save the answer to the current question"""
    
    result = interview_service.save_answer(interview_id, answer)
    if not result:
        raise HTTPException(status_code=400, detail="Failed to save answer. Interview not found or all questions already answered.")
    
    return JSONResponse(content={
        "success": True,
        "message": "Answer saved successfully"
    })

@router.post("/transcribe")
async def transcribe_audio(audio_data: Dict = Body(...)):
    """Transcribe audio to text"""
    
    if "audio" not in audio_data:
        raise HTTPException(status_code=400, detail="Audio data is required")
    
    try:
        result = interview_service.transcribe_audio(audio_data["audio"])
        
        if not result["success"]:
            error_message = result.get("error", "Unknown transcription error")
            raise HTTPException(status_code=400, detail=error_message)
        
        return JSONResponse(content={
            "success": True,
            "transcript": result["transcript"]
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")

@router.get("/{interview_id}/speech/{text}")
async def generate_speech(interview_id: str, text: str):
    """Generate speech from text"""
    
    # Check if the interview exists
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Get the current question
    current_question = interview_service.get_current_question(interview_id)
    
    lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
    if current_question and text == current_question["question"] and "audio_cache_path" in current_question:
        audio_cache_dir = f"interview_data/{interview_id}_audio"
        audio_content = interview_service.load_or_generate_cached_audio(
            audio_cache_dir,
            current_question["audio_cache_path"],
            text,
            lang,
        )
    else:
        audio_content = interview_service.generate_speech(text, language=lang)

    # Return audio as streaming response
    return StreamingResponse(
        io.BytesIO(audio_content),
        media_type="audio/mpeg"
    )

@router.post("/{interview_id}/evaluate")
async def evaluate_interview(interview_id: str):
    """Evaluate the interview"""
    
    result = interview_service.evaluate_interview(interview_id)
    
    # Check for success flag
    if not result.get("success", False):
        # Still return a 200 response with the error evaluation
        return JSONResponse(content={
            "success": False,
            "error": result.get("error", "Unknown error"),
            "evaluation": result.get("evaluation", {})
        })
    
    return JSONResponse(content={
        "success": True,
        "evaluation": result["evaluation"]
    })

@router.post("/{interview_id}/schedule-meet")
async def schedule_meet(interview_id: str, body: Dict = Body(...)):
    """
    Interviewer calls this endpoint after agreeing on a slot with the candidate.
    Creates a Google Meet event and emails the link to the candidate.

    Body: { "slot": "2026-04-08T10:00" }   (ISO 8601 datetime)
    """
    slot = body.get("slot")
    if not slot:
        raise HTTPException(status_code=400, detail="'slot' is required. Example: '2026-04-08T10:00'")

    result = interview_service.schedule_meet(interview_id, slot)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to schedule meeting"))

    return JSONResponse(content={
        "success": True,
        "meet_link": result["meet_link"],
        "slot": result["slot"],
        "email_sent": result["email_sent"],
        "message": f"Google Meet scheduled for {result['slot']}. Link emailed to candidate."
    })


@router.get("/{interview_id}/question_with_audio")
async def get_question_with_audio(interview_id: str):
    """Get the current question with audio for an interview session"""
    
    # Get the current question
    question_data = interview_service.get_current_question(interview_id)
    if not question_data:
        return JSONResponse(content={
            "success": False,
            "message": "No more questions or interview not found"
        })
    
    interview = interview_service.get_interview(interview_id)
    lang = (
        interview.get("language") or interview.get("metadata", {}).get("language", "en")
        if interview
        else "en"
    )
    audio_cache_dir = f"interview_data/{interview_id}_audio"
    audio_cache_file = question_data.get("audio_cache_path") or (
        f"{audio_cache_dir}/question_{question_data['index']}.mp3"
    )
    audio_content = interview_service.load_or_generate_cached_audio(
        audio_cache_dir, audio_cache_file, question_data["question"], lang
    )

    # Remove internal audio cache path from response
    if "audio_cache_path" in question_data:
        question_data.pop("audio_cache_path")
    
    # Convert audio to base64 for sending in JSON
    audio_base64 = base64.b64encode(audio_content).decode('ascii')
    
    return JSONResponse(content={
        "success": True,
        "question": question_data,
        "audio_base64": audio_base64
    })

@router.get("/{interview_id}/welcome")
async def get_welcome_message(interview_id: str):
    """Get the welcome message and audio for an interview session"""
    
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Get welcome message from metadata
    welcome_message = "Welcome to your interview."
    welcome_audio_path = None
    
    if "metadata" in interview and "welcome_message" in interview["metadata"]:
        welcome_message = interview["metadata"]["welcome_message"]
        welcome_audio_path = interview["metadata"].get("welcome_audio_path")
    
    audio_cache_dir = f"interview_data/{interview_id}_audio"
    welcome_path = welcome_audio_path or f"{audio_cache_dir}/welcome.mp3"
    lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
    audio_content = interview_service.load_or_generate_cached_audio(
        audio_cache_dir, welcome_path, welcome_message, lang
    )

    # Convert audio to base64 for sending in JSON
    audio_base64 = base64.b64encode(audio_content).decode('ascii')

    return JSONResponse(content={
        "success": True,
        "welcome_message": welcome_message,
        "audio_base64": audio_base64
    })

@router.get("/{interview_id}/question_audio/{index}")
async def get_question_audio(interview_id: str, index: int):
    """Get audio for a specific question by index - ensures synchronization"""
    
    # Get interview
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Validate question index
    if index < 0 or index >= len(interview["questions"]):
        raise HTTPException(status_code=400, detail="Invalid question index")
    
    # Get question text
    question_text = interview["questions"][index]["question"]
    
    # Look for cached audio
    audio_cache_dir = f"interview_data/{interview_id}_audio"
    audio_cache_file = f"{audio_cache_dir}/question_{index}.mp3"
    
    lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
    audio_content = interview_service.load_or_generate_cached_audio(
        audio_cache_dir, audio_cache_file, question_text, lang
    )

    # Return audio as streaming response
    return StreamingResponse(
        io.BytesIO(audio_content),
        media_type="audio/mpeg"
    )

@router.get("/{interview_id}/full_question/{index}")
async def get_full_question(interview_id: str, index: int):
    """
    Get complete question data including text, index, and audio in a single request.
    This ensures perfect synchronization between text and audio.
    """
    # Get interview session
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Check if index is valid
    if not interview["questions"] or index < 0 or index >= len(interview["questions"]):
        raise HTTPException(status_code=400, detail="Invalid question index")
    
    # Get question data
    question_text = interview["questions"][index]["question"]
    
    # Update the interview's current question index if needed
    # This is important to maintain the correct state in the backend
    if index > interview["current_question_index"]:
        # Only allow moving to the next question
        if index == interview["current_question_index"] + 1:
            # Save the previous question's answer if available
            if index > 0 and "answer" not in interview["questions"][index-1]:
                # Set empty answer if no answer was provided
                interview["questions"][index-1]["answer"] = ""
                
            # Update the current question index
            interview["current_question_index"] = index
            
            # Save the updated interview data
            with open(f"interview_data/{interview_id}.json", 'w') as f:
                json.dump(interview, f, indent=2)
    
    # Get or generate audio for the question
    audio_cache_dir = f"interview_data/{interview_id}_audio"
    os.makedirs(audio_cache_dir, exist_ok=True)
    audio_cache_file = f"{audio_cache_dir}/question_{index}.mp3"
    
    lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
    audio_content = interview_service.load_or_generate_cached_audio(
        audio_cache_dir, audio_cache_file, question_text, lang
    )

    # Convert audio to base64 for sending in JSON
    audio_base64 = base64.b64encode(audio_content).decode('ascii')

    # Return the complete question data
    return JSONResponse(content={
        "success": True,
        "question": {
            "text": question_text,
            "index": index,
            "total": len(interview["questions"])
        },
        "audio_base64": audio_base64
    })

@router.get("/{interview_id}/welcome_audio")
async def get_welcome_audio(interview_id: str):
    """Get welcome message with audio in a single request"""
    
    interview = interview_service.get_interview(interview_id)
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Get welcome message
    welcome_message = "Welcome to your interview. I will ask you a series of questions. Please answer each question clearly."
    if "metadata" in interview and "welcome_message" in interview["metadata"]:
        welcome_message = interview["metadata"]["welcome_message"]
    
    audio_cache_dir = f"interview_data/{interview_id}_audio"
    welcome_path = (
        interview.get("metadata", {}).get("welcome_audio_path")
        or f"{audio_cache_dir}/welcome.mp3"
    )
    lang = interview.get("language") or interview.get("metadata", {}).get("language", "en")
    audio_content = interview_service.load_or_generate_cached_audio(
        audio_cache_dir, welcome_path, welcome_message, lang
    )

    # Convert to base64
    audio_base64 = base64.b64encode(audio_content).decode('ascii')

    return JSONResponse(content={
        "success": True,
        "welcome_message": welcome_message,
        "audio_base64": audio_base64
    })
