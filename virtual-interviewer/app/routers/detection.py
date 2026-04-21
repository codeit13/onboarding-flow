from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import JSONResponse
from typing import Dict, Any
import json
import os
import logging
import base64
from app.services.detection_service import DetectionService

router = APIRouter(prefix="/api/detection", tags=["detection"])
detection_service = DetectionService()

# Configure logging
logger = logging.getLogger("detection-router")

@router.post("/{interview_id}/start")
async def start_detection(interview_id: str):
    """Start a new detection session"""
    session = detection_service.start_detection_session(interview_id)
    
    return JSONResponse(content={
        "success": True,
        "session_id": session["id"],
        "message": "Detection session started successfully"
    })

@router.post("/{interview_id}/stop")
async def stop_detection(interview_id: str):
    """Stop an active detection session"""
    result = detection_service.stop_detection_session(interview_id)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Detection session not found"))
    
    # Save the detection results to the interview session file
    try:
        interview_file = f"interview_data/{interview_id}.json"
        if os.path.exists(interview_file):
            with open(interview_file, 'r') as f:
                interview_data = json.load(f)
            
            # Get the final detection state
            session = result["session"]
            
            # Save the detection results to the interview data
            interview_data["detection_results"] = session["current_state"]
            
            # Also save a summary of the session
            interview_data["detection_summary"] = {
                "frames_processed": session["frames_processed"],
                "duration": session["end_time"] - session["start_time"],
                "history": session["history"][-5:] if "history" in session else []  # Save last 5 states
            }
            
            # Write the updated interview data back to the file
            with open(interview_file, 'w') as f:
                json.dump(interview_data, f, indent=2)
            
            logger.info(f"Saved detection results to interview session {interview_id}")
    except Exception as e:
        logger.error(f"Error saving detection results to interview: {str(e)}")
    
    return JSONResponse(content={
        "success": True,
        "message": "Detection session stopped successfully"
    })

@router.get("/{interview_id}/status")
async def get_detection_status(interview_id: str):
    """Get the current status of a detection session"""
    session = detection_service.get_detection_session(interview_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Detection session not found")
    
    return JSONResponse(content={
        "success": True,
        "active": session["active"],
        "current_state": session["current_state"],
        "frames_processed": session["frames_processed"]
    })

@router.post("/{interview_id}/process")
async def process_frame(
    interview_id: str, 
    data: Dict[str, Any] = Body(...)
):
    """Process a video frame for detection"""
    if "frame" not in data:
        raise HTTPException(status_code=400, detail="Frame data is required")
    
    result = detection_service.process_frame(interview_id, data["frame"])
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Processing failed"))
    
    # Periodically update the interview file with latest detection results
    frames_processed = result["frames_processed"]
    if frames_processed % 5 == 0:  # Update every 5 frames
        try:
            interview_file = f"interview_data/{interview_id}.json"
            if os.path.exists(interview_file):
                with open(interview_file, 'r') as f:
                    interview_data = json.load(f)
                
                # Save the current detection results
                interview_data["detection_results"] = result["detection_results"]
                
                # Write back to the file
                with open(interview_file, 'w') as f:
                    json.dump(interview_data, f, indent=2)
                
                logger.info(f"Updated detection results in interview {interview_id} (frame {frames_processed})")
        except Exception as e:
            logger.error(f"Error updating detection results in interview: {str(e)}")
    
    return JSONResponse(content={
        "success": True,
        "detection_results": result["detection_results"],
        "frames_processed": result["frames_processed"]
    }) 