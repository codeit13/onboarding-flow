import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.routers import interview, detection, users

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(title="Virtual Interviewer API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(interview.router)
app.include_router(detection.router)
app.include_router(users.router)

# Welcome endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to the Virtual Interviewer API"}

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    
    uvicorn.run("main:app", host=host, port=port, reload=True) 