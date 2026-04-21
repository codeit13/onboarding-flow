'use client'

import React, { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import Webcam from 'react-webcam'
import { playBeep, setupTabVisibilityDetection } from '@/utils/soundUtils'
import { useSearchParams } from 'next/navigation'

enum InterviewStatus {
  NOT_STARTED = 'not_started',
  IN_PROGRESS = 'in_progress',
  SUBMITTING = 'submitting',
  COMPLETED = 'completed'
}
interface Question {
  id: number
  text: string
  index: number
  total: number
}

interface InterviewSessionProps {
  interviewId: string
}

const InterviewSession: React.FC<InterviewSessionProps> = ({ interviewId }) => {
  const router = useRouter()
  const searchParams = useSearchParams()
  const questionCount = parseInt(searchParams.get('q') || '3')
  const getDuration = (q: number) => q === 3 ? 1200 : q === 4 ? 1500 : q === 5 ? 1800 : q === 6 ? 2100 : q === 7 ? 2400 : 2700

  const [question, setQuestion] = useState<Question | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [securityAlert, setSecurityAlert] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState<boolean>(false)
  const [audioData, setAudioData] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<string>('')
  const [isProcessing, setIsProcessing] = useState<boolean>(false)
  const [welcomePlayed, setWelcomePlayed] = useState<boolean>(false)
  const [questionAudioPlaying, setQuestionAudioPlaying] = useState<boolean>(false)
  const [showStartConfirm, setShowStartConfirm] = useState<boolean>(true)
  const [showSubmitConfirm, setShowSubmitConfirm] = useState<boolean>(false)
  const [interviewStarted, setInterviewStarted] = useState<boolean>(false)
  const [detectionRunning, setDetectionRunning] = useState<boolean>(false)
  const [verifiedName, setVerifiedName] = useState<string | null>(null)
  const [isVerifying, setIsVerifying] = useState<boolean>(false)
  const [timeRemaining, setTimeRemaining] = useState<number>(getDuration(questionCount)) // 30 minutes in seconds
  const [timerStarted, setTimerStarted] = useState<boolean>(false)

  const [interviewStatus, setInterviewStatus] = useState<InterviewStatus>(InterviewStatus.NOT_STARTED)



  // Critical ref to prevent race conditions
  const isNavigatingToResults = useRef<boolean>(false)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const webcamRef = useRef<Webcam | null>(null)
  const verificationInterval = useRef<NodeJS.Timeout | null>(null)
  const timerInterval = useRef<NodeJS.Timeout | null>(null)
  const securityAlertTimeout = useRef<NodeJS.Timeout | null>(null)

  // Auto-hide security alerts after 5 seconds
  useEffect(() => {
    if (securityAlert && !securityAlert.includes('Interview monitoring active')) {
      if (securityAlertTimeout.current) {
        clearTimeout(securityAlertTimeout.current)
      }
      securityAlertTimeout.current = setTimeout(() => {
        setSecurityAlert('Interview monitoring active - All systems normal')
      }, 5000)
    }
    return () => {
      if (securityAlertTimeout.current) {
        clearTimeout(securityAlertTimeout.current)
      }
    }
  }, [securityAlert])

  // Setup tab visibility detection and face verification
  useEffect(() => {
    if (interviewStarted && detectionRunning && interviewStatus === InterviewStatus.IN_PROGRESS) {
      // Set initial normal message
      setSecurityAlert('Interview monitoring active - All systems normal')

      startFaceVerification()

      const cleanup = setupTabVisibilityDetection(() => {
        playBeep(2000)
      })

      return () => {
        cleanup()
        if (verificationInterval.current) {
          clearInterval(verificationInterval.current)
        }
      }
    }
  }, [interviewStarted, detectionRunning, interviewStatus])

  // Main 30-minute timer effect - starts after welcome message and runs for entire interview
  useEffect(() => {
    if (timerStarted && !isLoading && !showStartConfirm && !showSubmitConfirm && interviewStatus === InterviewStatus.IN_PROGRESS) {
      timerInterval.current = setInterval(() => {
        setTimeRemaining((prev) => {
          if (prev <= 1) {
            if (timerInterval.current) {
              clearInterval(timerInterval.current)
            }
            setShowSubmitConfirm(true)
            return 0
          }
          return prev - 1
        })
      }, 1000)

      return () => {
        if (timerInterval.current) {
          clearInterval(timerInterval.current)
        }
      }
    }
  }, [timerStarted, showStartConfirm, showSubmitConfirm, interviewStatus])

  // Initialize interview
  useEffect(() => {
    if (!interviewId || isNavigatingToResults.current) return

    const initializeInterview = async () => {
      setIsLoading(true)
      try {
        if (interviewStarted && interviewStatus === InterviewStatus.IN_PROGRESS) {
          if (!welcomePlayed) {
            await playWelcomeMessage()
          }
        }
      } catch (err) {
        console.error('Error initializing interview:', err)
        setError('Failed to start the interview. Please try again.')
      } finally {
        setIsLoading(false)
      }
    }

    initializeInterview()
  }, [interviewId, welcomePlayed, interviewStarted, interviewStatus])

  const handleStartConfirm = async () => {
    if (interviewStatus !== InterviewStatus.NOT_STARTED) return

    setShowStartConfirm(false)
    setInterviewStarted(true)
    setDetectionRunning(true)
    setInterviewStatus(InterviewStatus.IN_PROGRESS)

    try {
      await axios.post(`/api/detection/${interviewId}/start`)
      console.log("Detection started successfully")
    } catch (err) {
      console.error("Error starting detection:", err)
    }
  }

  const handleSubmitConfirm = async () => {
    // IMMEDIATE prevention of race conditions
    if (isNavigatingToResults.current || interviewStatus === InterviewStatus.COMPLETED) {
      console.log("Already navigating or completed, ignoring submit")
      return
    }

    console.log("=== STARTING INTERVIEW SUBMISSION ===")
    isNavigatingToResults.current = true
    setInterviewStatus(InterviewStatus.SUBMITTING)

    // IMMEDIATELY stop all processes
    setDetectionRunning(false)
    setIsRecording(false)
    setIsProcessing(false)
    setQuestionAudioPlaying(false)

    // Stop media recorder immediately
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        mediaRecorderRef.current.stop()
      } catch (e) {
        console.log("MediaRecorder already stopped")
      }
    }

    // Stop audio immediately
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }

    // Clear all intervals/timeouts immediately
    if (verificationInterval.current) {
      clearInterval(verificationInterval.current)
      verificationInterval.current = null
    }
    if (timerInterval.current) {
      clearInterval(timerInterval.current)
      timerInterval.current = null
    }
    if (securityAlertTimeout.current) {
      clearTimeout(securityAlertTimeout.current)
      securityAlertTimeout.current = null
    }

    // API calls in background (don't await)
    axios.post(`/api/detection/${interviewId}/stop`).catch(err => {
      console.error("Error stopping detection:", err)
    })

    // IMMEDIATE navigation
    console.log("=== NAVIGATING TO RESULTS IMMEDIATELY ===")
    setInterviewStatus(InterviewStatus.COMPLETED)

    // Use replace instead of push to prevent back navigation issues
    router.replace(`/virtual-interviewer/${interviewId}/results`)
  }

  const playWelcomeMessage = async () => {
    try {
      console.log('Starting welcome message...')

      const response = await axios.get(`/api/interview/${interviewId}/welcome_audio`)

      if (response.data.success) {
        const audioBase64 = response.data.audio_base64

        const byteCharacters = atob(audioBase64)
        const byteNumbers = new Array(byteCharacters.length)
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i)
        }
        const byteArray = new Uint8Array(byteNumbers)
        const audioBlob = new Blob([byteArray], { type: 'audio/mpeg' })

        const audioUrl = URL.createObjectURL(audioBlob)
        const audio = new Audio(audioUrl)
        audioRef.current = audio

        audio.onended = async () => {
          console.log('Welcome message ended, cleaning up and preparing first question...')

          // STEP 1: Clean up welcome audio completely
          if (audioRef.current) {
            audioRef.current.pause()
            audioRef.current.currentTime = 0
            audioRef.current.src = ''
            audioRef.current.load()
            audioRef.current = null
          }

          // STEP 2: Clean up URL to free memory
          URL.revokeObjectURL(audioUrl)

          // STEP 3: Add delay to ensure audio context is fully cleared
          console.log('Adding delay before first question...')
          await new Promise(resolve => setTimeout(resolve, 800))

          // STEP 4: Set state to indicate welcome is complete and start the main timer
          setWelcomePlayed(true)
          setTimerStarted(true) // Start the 30-minute timer here

          // STEP 5: Add another small delay after state update
          await new Promise(resolve => setTimeout(resolve, 200))

          // STEP 6: Load first question
          console.log('Loading first question...')

        }

        audio.onerror = (error) => {
          console.error('Welcome audio error:', error)
          setWelcomePlayed(true)
          setTimerStarted(true) // Start timer even on error
          setTimeout(() => loadQuestionWithAudio(0), 500)
        }

        console.log('Playing welcome message...')
        await audio.play()
      } else {
        throw new Error('Failed to get welcome audio')
      }
    } catch (err) {
      console.error('Error playing welcome message:', err)

      // Clean up any audio reference on error
      if (audioRef.current) {
        audioRef.current = null
      }

      setWelcomePlayed(true)
      setTimerStarted(true) // Start timer even on error

      // Add delay even on error to prevent timing issues with first question
      await new Promise(resolve => setTimeout(resolve, 500))

    }
  }

  const loadQuestionWithAudio = async (index: number) => {
    try {
      setIsLoading(true)

      const response = await axios.get(`/api/interview/${interviewId}/full_question/${index}`)

      if (response.data.success) {
        setQuestion(response.data.question)
        setTranscript('') // Clear previous transcript

        const audioBase64 = response.data.audio_base64

        const byteCharacters = atob(audioBase64)
        const byteNumbers = new Array(byteCharacters.length)
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i)
        }
        const byteArray = new Uint8Array(byteNumbers)
        const audioBlob = new Blob([byteArray], { type: 'audio/mpeg' })

        const audioUrl = URL.createObjectURL(audioBlob)
        const audio = new Audio(audioUrl)
        audioRef.current = audio

        setQuestionAudioPlaying(true)
        audio.onended = () => {
          setQuestionAudioPlaying(false)
          // No need to reset or restart timer - it continues running
        }

        await audio.play()
      } else {
        setShowSubmitConfirm(true)
      }
    } catch (err: any) {
      console.error(`Error loading question ${index}:`, err)

      if (err.response && err.response.status === 400) {
        setShowSubmitConfirm(true)
      } else {
        setError(`Failed to load question ${index + 1}. Please try again.`)
      }
    } finally {
      setIsLoading(false)
    }
  }

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' })
        const reader = new FileReader()
        reader.readAsDataURL(audioBlob)
        reader.onloadend = () => {
          const base64data = reader.result as string
          setAudioData(base64data)
          transcribeAudio(base64data)
        }

        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
    } catch (err) {
      console.error('Error starting recording:', err)
      setError('Failed to access microphone. Please check your permissions and try again.')
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop()
      setIsRecording(false)
    }
  }

  const transcribeAudio = async (audioBase64: string) => {
    try {
      setIsProcessing(true)

      const response = await axios.post(`/api/interview/transcribe`, {
        audio: audioBase64
      })

      if (response.data.success) {
        setTranscript(response.data.transcript)
        await saveAnswer(response.data.transcript)
      } else {
        setError('Failed to transcribe audio. Please try again.')
      }
    } catch (err) {
      console.error('Error transcribing audio:', err)
      setError('An error occurred while processing your response. Please try again.')
    } finally {
      setIsProcessing(false)
    }
  }

  const saveAnswer = async (answer: string) => {
    if (!question) return

    try {
      await axios.post(`/api/interview/${interviewId}/answer`, {
        answer
      })

      setAudioData(null)
      setTranscript('')

      const nextIndex = question.index + 1

      if (nextIndex >= question.total) {
        // This was the last question, show submit confirmation
        setShowSubmitConfirm(true)
      } else {
        // Load next question (timer continues running)
        await loadQuestionWithAudio(nextIndex)
      }
    }
    catch (err) {
      console.error('Error saving answer:', err)
      setError('Failed to save your answer. Please try again.')
    }
  }

  const getProgressPercentage = () => {
    if (!question) return 0
    return ((question.index) / question.total) * 100
  }

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const getTimeColor = () => {
    if (timeRemaining <= 300) return '#ef4444' // Red for last 5 minutes
    if (timeRemaining <= 600) return '#f59e0b' // Orange for last 10 minutes
    return 'white'
  }

  const startFaceVerification = () => {
    verificationInterval.current = setInterval(async () => {
      if (webcamRef.current && !isVerifying) {
        const imageSrc = webcamRef.current.getScreenshot()
        if (imageSrc) {
          setIsVerifying(true)
          try {
            const verifyResponse = await axios.post(
              `/api/interview/${interviewId}/verify_face`,
              { photo: imageSrc }
            )

            if (verifyResponse.data.success) {
              if (verifyResponse.data.match) {
                setVerifiedName(verifyResponse.data.name)
                // Reset to normal message if currently showing verification alerts
                if (securityAlert && (securityAlert.includes('No face detected') || securityAlert.includes('Face verification failed'))) {
                  setSecurityAlert('Interview monitoring active - All systems normal')
                }
              } else {
                setVerifiedName(null)
                if (verifyResponse.data.message?.includes("No face detected")) {
                  setSecurityAlert('⚠️ No face detected - Please ensure your face is visible to the camera')
                } else {
                  setSecurityAlert('⚠️ Face verification failed - Please ensure you are the same person who started the interview')
                }
              }
            }

            try {
              const detectionResponse = await axios.post(
                `/api/detection/${interviewId}/process`,
                { frame: imageSrc }
              )

              if (detectionResponse.data.success) {
                console.log('Detection results:', detectionResponse.data.detection_results)

                if (detectionResponse.data.detection_results.people_count > 1) {
                  setSecurityAlert('🚨 Multiple people detected - This may be considered cheating!')
                  playBeep(1000)
                } else if (detectionResponse.data.detection_results.communication_device_present) {
                  setSecurityAlert('📱 Communication device detected - This may be considered cheating!')
                  playBeep(1000)
                } else if (detectionResponse.data.detection_results.direction_looking !== 'at-system') {
                  setSecurityAlert('👀 Please look at the screen - Maintain eye contact with camera')
                } else if (verifyResponse.data.match) {
                  // Only set normal message if no other issues detected
                  setSecurityAlert('✅ Interview monitoring active - All systems normal')
                }
              }
            } catch (detectionErr) {
              console.error('Error with detection service:', detectionErr)
            }
          } catch (err) {
            console.error('Error with face verification:', err)
          } finally {
            setIsVerifying(false)
          }
        }
      }
    }, 2000)
  }

  const getSecurityAlertStyle = () => {
    if (!securityAlert) return {}

    if (securityAlert.includes('All systems normal')) {
      return {
        backgroundColor: 'rgba(6, 169, 156, 0.1)',
        borderColor: 'var(--x-green-100)',
        color: 'var(--x-green-100)'
      }
    } else if (securityAlert.includes('No face detected') || securityAlert.includes('Face verification failed') || securityAlert.includes('Please look at the screen')) {
      return {
        backgroundColor: 'rgba(255, 188, 64, 0.1)',
        borderColor: 'var(--x-orange-300)',
        color: '#d97706'
      }
    } else {
      return {
        backgroundColor: 'rgba(239, 68, 68, 0.1)',
        borderColor: '#ef4444',
        color: '#dc2626'
      }
    }
  }

  return (
    <div className="min-h-screen" style={{ background: 'linear-gradient(135deg, var(--x-purple-300) 0%, var(--x-purple-400) 50%, var(--dark-bg-color) 100%)' }}>
      <div className="max-w-screen-2xl h-full mx-auto px-6 py-8">
        {/* Xebia Header */}
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-bold text-white mb-2">Xebia Virtual Interview</h1>
          <div className="w-24 h-1 bg-white mx-auto rounded-full opacity-80"></div>
        </div>

        {/* General Error Messages - only for non-security related errors */}
        {error && (
          <div className="mb-6 p-4 bg-red-50 border-l-4 border-red-500 text-red-800 rounded-r-lg shadow-lg">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <p className="font-medium">{error}</p>
              </div>
            </div>
          </div>
        )}

        {showStartConfirm && (
          <div className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50 backdrop-blur-sm">
            <div className="bg-white rounded-3xl p-10 max-w-lg mx-4 shadow-2xl border border-gray-100">
              <div className="text-center">
                <div className="mb-6">
                  <div className="w-20 h-20 mx-auto rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--x-purple-300)' }}>
                    <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1.01M15 10h1.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                </div>
                <h2 className="text-3xl font-bold text-gray-900 mb-4">Ready to Begin?</h2>
                <p className="text-gray-600 mb-8 leading-relaxed">Welcome to your Xebia interview session. You have {Math.floor(getDuration(questionCount) / 60)} minutes to complete {questionCount} questions. Once you start, our AI interviewer will guide you through the process with personalized questions.</p>
                <div className="flex space-x-4">
                  <button
                    onClick={handleStartConfirm}
                    className="flex-1 px-8 py-4 text-white rounded-2xl font-semibold text-lg transition-all duration-300 transform hover:scale-105 shadow-lg"
                    style={{
                      background: 'linear-gradient(135deg, var(--x-purple-300), var(--x-purple-400))',
                      boxShadow: '0 10px 25px rgba(74, 30, 71, 0.3)'
                    }}
                  >
                    Start Interview
                  </button>
                  <button
                    onClick={() => router.push('/virtual-interviewer')}
                    className="flex-1 px-8 py-4 border-2 text-gray-700 rounded-2xl font-semibold text-lg transition-all duration-300 hover:bg-gray-50 shadow-lg"
                    style={{ borderColor: 'var(--x-purple-300)' }}
                  >
                    Go Back
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {showSubmitConfirm && (
          <div className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50 backdrop-blur-sm">
            <div className="bg-white rounded-3xl p-10 max-w-lg mx-4 shadow-2xl border border-gray-100">
              <div className="text-center">
                <div className="mb-6">
                  <div className="w-20 h-20 mx-auto rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--x-green-100)' }}>
                    <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                  </div>
                </div>
                <h2 className="text-3xl font-bold text-gray-900 mb-4">Interview Complete!</h2>
                <p className="text-gray-600 mb-8 leading-relaxed">
                  {timeRemaining <= 0
                    ? "Time's up! Your 30-minute interview session has ended. Would you like to submit your responses?"
                    : "Congratulations! You've successfully completed your Xebia interview. Would you like to submit your responses?"
                  }
                </p>
                <div className="flex space-x-4">
                  <button
                    onClick={handleSubmitConfirm}
                    className="flex-1 px-8 py-4 text-white rounded-2xl font-semibold text-lg transition-all duration-300 transform hover:scale-105 shadow-lg"
                    style={{
                      background: 'linear-gradient(135deg, var(--x-green-100), var(--x-green-200))',
                      boxShadow: '0 10px 25px rgba(6, 169, 156, 0.3)'
                    }}
                  >
                    Submit Interview
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {isLoading && !showStartConfirm && !showSubmitConfirm && (
          <div className="flex items-center justify-center min-h-[calc(100vh-12rem)]">
            <div className="text-center">
              <div className="inline-flex items-center justify-center w-20 h-20 rounded-full mb-6" style={{ backgroundColor: 'rgba(255, 255, 255, 0.2)' }}>
                <div className="w-10 h-10 border-4 border-white border-t-transparent rounded-full animate-spin"></div>
              </div>
              <p className="text-white text-xl font-medium">Preparing your interview...</p>
            </div>
          </div>
        )}

        {!isLoading && !showStartConfirm && !showSubmitConfirm && question && (
          <div className="grid lg:grid-cols-3 gap-6 h-[calc(100vh-12rem)]">
            <div className="lg:col-span-2 flex flex-col h-full">
              {/* Fixed Security Status Bar - Always Present */}
              <div className="mb-4 h-16 flex items-center flex-shrink-0">
                <div
                  className="w-full p-3 rounded-lg shadow-lg border-2 transition-all duration-300"
                  style={getSecurityAlertStyle()}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      <div className="w-2 h-2 rounded-full mr-3 animate-pulse"
                        style={{
                          backgroundColor: securityAlert?.includes('All systems normal') ? 'var(--x-green-100)' :
                            securityAlert?.includes('Multiple people') || securityAlert?.includes('Communication device') ? '#ef4444' : '#d97706'
                        }}>
                      </div>
                      <p className="font-medium text-sm">
                        {securityAlert || 'Initializing security monitoring...'}
                      </p>
                    </div>
                    <div className="text-xs opacity-70 font-medium">
                      Live Monitoring
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white flex-1 rounded-2xl shadow-xl overflow-hidden border border-white/20 flex flex-col">
                <div className="p-5 flex-shrink-0" style={{ background: 'linear-gradient(135deg, var(--x-purple-300), var(--x-purple-400))' }}>
                  <div className="flex items-center justify-between text-white mb-4">
                    <div>
                      <h2 className="text-xl font-bold">Interview Progress</h2>
                      <p className="text-white/80 text-sm">Powered by Xebia AI</p>
                    </div>
                    <div className="text-right">
                      <span className="text-white/90 text-base font-medium">
                        Question {question.index + 1} of {question.total}
                      </span>
                      {timerStarted && (
                        <div className="mt-1 flex flex-col items-end">
                          <div className="text-xs text-white/70 mb-1">Time Remaining</div>
                          <div className="text-2xl font-bold" style={{ color: getTimeColor() }}>
                            {formatTime(timeRemaining)}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="w-full bg-white/20 rounded-full h-3 overflow-hidden">
                    <div
                      className="bg-white h-3 rounded-full transition-all duration-500 ease-out shadow-lg"
                      style={{ width: `${getProgressPercentage()}%` }}
                    ></div>
                  </div>
                </div>

                <div className="p-6 flex flex-col justify-between flex-1">
                  <div className="mb-6">
                    <h4 className="text-2xl font-bold text-gray-900 leading-relaxed">{question.text}</h4>
                    <div className="w-12 h-1 mt-3 rounded-full" style={{ backgroundColor: 'var(--x-purple-300)' }}></div>
                  </div>

                  <div className="flex-1 flex flex-col justify-end">
                    {!isRecording && !isProcessing && !transcript && (
                      <button
                        onClick={startRecording}
                        disabled={questionAudioPlaying || !verifiedName || timeRemaining <= 0}
                        className="w-full flex items-center justify-center px-8 py-4 text-white text-lg font-bold rounded-xl transition-all duration-300 transform hover:scale-[1.01] disabled:opacity-60 disabled:cursor-not-allowed disabled:transform-none shadow-lg"
                        style={{
                          background: questionAudioPlaying || !verifiedName || timeRemaining <= 0
                            ? 'var(--x-grey-500)'
                            : 'linear-gradient(135deg, var(--x-purple-300), var(--x-purple-400))',
                          boxShadow: questionAudioPlaying || !verifiedName || timeRemaining <= 0
                            ? 'none'
                            : '0 10px 25px rgba(74, 30, 71, 0.3)'
                        }}
                      >
                        <svg className="w-6 h-6 mr-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clipRule="evenodd" />
                        </svg>
                        {timeRemaining <= 0 ? 'Interview time expired' :
                          questionAudioPlaying ? 'Please wait for question to finish...' :
                            !verifiedName ? 'Verifying identity...' : 'Record Your Answer'}
                      </button>
                    )}

                    {isRecording && (
                      <div className="text-center">
                        <button
                          onClick={stopRecording}
                          className="inline-flex items-center px-8 py-4 bg-red-600 text-white text-lg font-bold rounded-xl hover:bg-red-700 transition-all duration-300 transform hover:scale-105 shadow-lg"
                        >
                          <div className="w-5 h-5 bg-white rounded-sm mr-3"></div>
                          Stop Recording
                        </button>
                        <div className="mt-4 flex items-center justify-center text-red-600">
                          <div className="animate-pulse w-3 h-3 bg-red-600 rounded-full mr-2"></div>
                          <span className="text-base font-semibold">Recording in progress...</span>
                        </div>
                      </div>
                    )}

                    {isProcessing && (
                      <div className="text-center py-8">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4" style={{ backgroundColor: 'rgba(74, 30, 71, 0.1)' }}>
                          <div className="w-8 h-8 border-4 border-t-transparent rounded-full animate-spin" style={{ borderColor: 'var(--x-purple-300)' }}></div>
                        </div>
                        <p className="text-gray-600 text-lg font-medium">Analyzing your response...</p>
                      </div>
                    )}

                    {transcript && (
                      <div className="mt-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
                        <h5 className="text-sm font-semibold text-gray-700 mb-2">Your Response:</h5>
                        <p className="text-gray-900 text-sm leading-relaxed">{transcript}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-1 h-full">
              <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-white/20 h-full flex flex-col">
                <div className="p-4 flex-shrink-0" style={{ background: 'linear-gradient(135deg, var(--x-purple-300), var(--x-purple-400))' }}>
                  <h5 className="text-lg font-bold text-white text-center">Identity Verification</h5>
                </div>
                <div className="p-6 flex-1 flex flex-col">
                  <div className="text-center mb-4 flex-1 w-full flex justify-center">
                    <div className="relative inline-block w-full mx-auto">
                      <Webcam
                        ref={webcamRef}
                        audio={false}
                        screenshotFormat="image/jpeg"
                        className="w-full rounded-xl border-4 shadow-lg aspect-[4/3]"
                        style={{ borderColor: verifiedName ? 'var(--x-green-100)' : 'var(--x-purple-300)' }}
                        videoConstraints={{ width: { ideal: 320 }, height: { ideal: 240 }, facingMode: 'user' }}
                        mirrored={true}
                      />
                      {isVerifying && !isRecording && (
                        <div className="absolute top-2 left-2 px-2 py-1 rounded-full text-xs font-bold text-white animate-pulse" style={{ backgroundColor: 'var(--x-blue-100)' }}>
                          Analyzing...
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="space-y-3 flex-shrink-0">
                    {verifiedName ? (
                      <div className="p-3 rounded-lg border shadow-md" style={{ backgroundColor: 'rgba(6, 169, 156, 0.1)', borderColor: 'var(--x-green-100)' }}>
                        <div className="flex items-center">
                          <svg className="w-5 h-5 mr-2" style={{ color: 'var(--x-green-100)' }} fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                          </svg>
                          <div>
                            <span className="text-xs font-bold" style={{ color: 'var(--x-green-100)' }}>Verified Identity</span>
                            <p className="text-gray-700 font-medium text-sm">{verifiedName}</p>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="p-3 rounded-lg border shadow-md" style={{ backgroundColor: 'rgba(255, 188, 64, 0.1)', borderColor: 'var(--x-orange-300)' }}>
                        <div className="flex items-center">
                          <svg className="w-5 h-5 mr-2" style={{ color: 'var(--x-orange-300)' }} fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                          </svg>
                          <div>
                            <span className="text-xs font-bold" style={{ color: 'var(--x-orange-300)' }}>Verifying Identity</span>
                            <p className="text-gray-700 text-xs">Please ensure your face is clearly visible</p>
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="text-center">
                      <div className="p-3 rounded-lg" style={{ backgroundColor: 'rgba(74, 30, 71, 0.05)' }}>
                        <p className="text-xs text-gray-600 leading-relaxed">
                          <span className="font-semibold" style={{ color: 'var(--x-purple-300)' }}>Xebia Security:</span> Real-time monitoring ensures interview integrity.
                          Please maintain eye contact with the camera and remain alone in the frame.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default InterviewSession