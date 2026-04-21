# Virtual Interviewer API

## Overview
This API provides endpoints for conducting virtual interviews with AI-generated questions and evaluations.

## Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Run the application: `python main.py`

## API Usage Guide

### Start an Interview
```
POST /api/interview/start
```
- Optionally upload a resume file
- Returns the interview ID and a welcome message
- **Example response:**
```json
{
    "success": true,
    "interview_id": "20230425201906",
    "message": "Interview session created successfully",
    "welcome_message": "Welcome to your interview. I will ask you a series of questions. Please answer each question clearly."
}
```

### Get Welcome Audio
```
GET /api/interview/{interview_id}/welcome_audio
```
- Returns the welcome message with audio as base64
- **Example response:**
```json
{
    "success": true,
    "welcome_message": "Welcome to your interview. I will ask you a series of questions. Please answer each question clearly.",
    "audio_base64": "base64_encoded_audio_data"
}
```

### Get Question with Audio (RECOMMENDED)
```
GET /api/interview/{interview_id}/full_question/{index}
```
- Get the question text and audio in a single request
- The `index` is zero-based (0 = first question)
- Returns question text, index information, and audio as base64
- **Example response:**
```json
{
    "success": true,
    "question": {
        "text": "Tell me about your experience with Python programming.",
        "index": 0,
        "total": 5
    },
    "audio_base64": "base64_encoded_audio_data"
}
```

### Save Answer
```
POST /api/interview/{interview_id}/answer
```
- Body: `{"answer": "Your answer text here"}`
- Saves the answer to the current question and advances to the next question
- **Example response:**
```json
{
    "success": true,
    "message": "Answer saved successfully"
}
```

### Evaluate Interview
```
POST /api/interview/{interview_id}/evaluate
```
- Evaluates the completed interview
- **Example response:**
```json
{
    "success": true,
    "evaluation": {
        "Overall assessment": "...",
        "Strengths identified": ["...", "..."],
        "Areas for improvement": ["...", "..."],
        "Technical skills assessment": "...",
        "Communication skills assessment": "...",
        "Final recommendation": "..."
    }
}
```

### Transcribe Audio
```
POST /api/interview/transcribe
```
- Body: `{"audio": "base64_encoded_audio_data"}`
- Transcribes audio to text
- **Example response:**
```json
{
    "success": true,
    "transcript": "Transcribed text here"
}
```

## Frontend Integration Guide

For proper synchronization between text and audio, follow these steps:

1. Start the interview:
   ```javascript
   // Start interview and get welcome message
   const startResponse = await fetch('/api/interview/start', {...})
   const startData = await startResponse.json()
   const interviewId = startData.interview_id
   ```

2. Play welcome message:
   ```javascript
   // Get welcome audio
   const welcomeResponse = await fetch(`/api/interview/${interviewId}/welcome_audio`)
   const welcomeData = await welcomeResponse.json()
   
   // Play welcome audio
   playAudio(welcomeData.audio_base64)
   ```

3. Get first question with audio:
   ```javascript
   // Get first question (index 0) with its audio
   const questionResponse = await fetch(`/api/interview/${interviewId}/full_question/0`)
   const questionData = await questionResponse.json()
   
   // Display question
   displayQuestion(questionData.question.text)
   
   // Play question audio
   playAudio(questionData.audio_base64)
   ```

4. Save answer and get next question:
   ```javascript
   // Save answer to current question
   await fetch(`/api/interview/${interviewId}/answer`, {
     method: 'POST',
     body: JSON.stringify({ answer: userAnswer }),
     headers: { 'Content-Type': 'application/json' }
   })
   
   // Get next question with its audio (increment index)
   const nextIndex = currentIndex + 1
   const nextQuestionResponse = await fetch(`/api/interview/${interviewId}/full_question/${nextIndex}`)
   const nextQuestionData = await nextQuestionResponse.json()
   
   // Display question
   displayQuestion(nextQuestionData.question.text)
   
   // Play question audio
   playAudio(nextQuestionData.audio_base64)
   ```

This approach ensures perfect synchronization between the displayed question and its audio. 
