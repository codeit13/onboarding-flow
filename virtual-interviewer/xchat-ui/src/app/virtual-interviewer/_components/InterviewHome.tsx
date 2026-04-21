'use client'

import React, { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import axios, { AxiosError } from 'axios'
import Webcam from 'react-webcam'
import Lottie from 'lottie-react'

// Import your robot animation JSON

import penguinAnimation from '../_animations/penguin.json'

// API Configuration


const dataURLtoBlob = (dataurl: string): Blob => {
  const arr = dataurl.split(",");
  const mimeMatch = arr[0].match(/:(.*?);/);
  if (!mimeMatch) {
    throw new Error("Invalid data URL");
  }
  const mime = mimeMatch[1];
  const bstr = atob(arr[1]);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n);
  }
  return new Blob([u8arr], { type: mime });
};

const InterviewHome: React.FC = () => {
  const router = useRouter()
  const [mounted, setMounted] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState<string>('')
  const [email, setEmail] = useState<string>('')
  const [jdFile, setJdFile] = useState<File | null>(null)
  const [jdText, setJdText] = useState<string>('')
  const [jdInputType, setJdInputType] = useState<'file' | 'text'>('file')
  const [questionCount, setQuestionCount] = useState<number>(3)
  const [isLoading, setIsLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [showCamera, setShowCamera] = useState<boolean>(false)
  const [capturedImage, setCapturedImage] = useState<string | null>(null)
  const [currentStep, setCurrentStep] = useState<number>(1)
  const webcamRef = useRef<Webcam | null>(null)

  // Ensure component is mounted on client
  useEffect(() => {
    setMounted(true)
    document.documentElement.style.overflow = 'hidden'
    document.body.style.overflow = 'hidden'
    document.body.style.height = '100vh'
    document.documentElement.style.height = '100vh'

    return () => {
      document.documentElement.style.overflow = 'auto'
      document.body.style.overflow = 'auto'
      document.body.style.height = 'auto'
      document.documentElement.style.height = 'auto'
    }
  }, [])

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      setFile(event.target.files[0])
    }
  }

  const handleJdFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      setJdFile(event.target.files[0])
    }
  }

  const handleNameChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setName(event.target.value)
  }

  const handleQuestionCountChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setQuestionCount(Number(event.target.value))
  }

  const handleCameraToggle = () => {
    setShowCamera(prev => !prev)
    if (showCamera && capturedImage) {
      setCapturedImage(null)
    }
  }

  const capturePhoto = () => {
    if (webcamRef.current) {
      const imageSrc = webcamRef.current.getScreenshot()
      if (imageSrc) {
        setCapturedImage(imageSrc)
        setShowCamera(false)
        setError(null)
      } else {
        setError("Could not capture photo. Please try again.")
      }
    }
  }

  const handleNextStep = () => {
    if (currentStep === 1) {
      if (!name.trim()) {
        setError('Please enter your name')
        return
      }
      setError(null)
      setCurrentStep(2)
    }
  }

  const handlePrevStep = () => {
    if (currentStep === 2) {
      setCurrentStep(1)
      setError(null)
    }
  }

  const startInterview = async (event: React.FormEvent) => {
    event.preventDefault()

    if (!name.trim()) {
      setError('Please enter your name')
      return
    }

    if (!capturedImage) {
      setError('Please capture your photo')
      return
    }

    setIsLoading(true)
    setError(null)

    // Add minimum loading duration to make the spinner visible
    const startTime = Date.now()
    const minLoadingTime = 2000 // 1.5 seconds minimum

    const formData = new FormData()
    if (file) {
      formData.append('resume_file', file)
    }
    if (jdInputType === 'file' && jdFile) {
      formData.append('jd_file', jdFile)
    } else if (jdInputType === 'text' && jdText.trim()) {
      formData.append('jd_text', jdText.trim())
    }
    formData.append('name', name.trim())
    if (email.trim()) {
      formData.append('email', email.trim())
    }
    formData.append('photo', capturedImage)
    formData.append('question_count', questionCount.toString())

    // try {
    //   const photoBlob = dataURLtoBlob(capturedImage);
    //   // The third argument is the filename the backend will see
    //   formData.append("photo", photoBlob, "photo.jpg");
    // } catch (e) {
    //   setError("Failed to process captured image. Please try again.");
    //   setIsLoading(false);
    //   return;
    // }

    try {
      const response = await axios.post(
        `/api/interview/start`,
        formData,
        {
          timeout: 20000,
        }
      )

      // Ensure minimum loading time has passed
      const elapsedTime = Date.now() - startTime
      const remainingTime = Math.max(0, minLoadingTime - elapsedTime)

      if (remainingTime > 0) {
        await new Promise(resolve => setTimeout(resolve, remainingTime))
      }

      if (response.data && response.data.interview_id) {
        router.push(`/virtual-interviewer/${response.data.interview_id}?q=${questionCount}`)
      } else {
        const responseDataStr = response.data ? JSON.stringify(response.data) : "empty response"
        setError(`Failed to start interview: Could not retrieve a valid interview ID. Server response: ${responseDataStr}`)
      }
    } catch (err) {
      // Ensure minimum loading time has passed even on error
      const elapsedTime = Date.now() - startTime
      const remainingTime = Math.max(0, minLoadingTime - elapsedTime)

      if (remainingTime > 0) {
        await new Promise(resolve => setTimeout(resolve, remainingTime))
      }

      const axiosError = err as AxiosError<{ message?: string; detail?: any }>
      console.error('Error starting interview:', axiosError)

      if (axiosError.response) {
        const responseData = axiosError.response.data
        let errorMessage = `Server Error: ${axiosError.response.status}.`

        if (responseData && typeof responseData === 'object') {
          if (responseData.message) {
            errorMessage = `Error: ${responseData.message}`
          } else if (responseData.detail) {
            if (Array.isArray(responseData.detail) && responseData.detail.length > 0) {
              const firstError = responseData.detail[0]
              errorMessage = `Validation Error: ${firstError.msg} (field: ${firstError.loc.join('.')})`
            } else {
              errorMessage += ` ${JSON.stringify(responseData)}`
            }
          } else {
            errorMessage += ` ${JSON.stringify(responseData)}`
          }
        } else if (responseData) {
          errorMessage += ` ${responseData}`
        }
        setError(errorMessage)
      } else if (axiosError.request) {
        setError('Network error. Please check your connection and try again.')
      } else {
        setError('An unexpected error occurred while preparing the interview request. Please try again.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleInputFocus = (e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.currentTarget.style.borderColor = 'var(--x-purple-200)'
    e.currentTarget.style.boxShadow = '0 0 0 2px rgba(230, 161, 219, 0.2)'
  }

  const handleInputBlur = (e: React.FocusEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.currentTarget.style.borderColor = 'var(--x-white-500)'
    e.currentTarget.style.boxShadow = 'none'
  }

  // Loading state
  if (!mounted) {
    return (
      <div className="fixed inset-0 flex items-center justify-center z-50" style={{ backgroundColor: 'var(--x-purple-300)' }}>
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-white rounded-full shadow-lg mb-6">
            <svg className="animate-spin w-10 h-10" style={{ color: 'var(--x-purple-300)' }} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">Loading Virtual Interviewer</h2>
          <p className="text-white/80">Preparing your interview experience...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen relative overflow-hidden" style={{ backgroundColor: 'var(--x-purple-300)' }}>

      {/* Full Screen Loading Overlay for Interview Start */}
      {isLoading && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white rounded-3xl p-8 shadow-2xl text-center max-w-sm mx-4">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4" style={{ backgroundColor: 'var(--x-purple-200)' }}>
              <svg className="animate-spin w-8 h-8 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </div>
            <h3 className="text-xl font-bold mb-2" style={{ color: 'var(--x-grey-300)' }}>
              Preparing Your Interview
            </h3>
            <p className="text-sm" style={{ color: 'var(--x-grey-100)' }}>
              Setting up your personalized interview experience...
            </p>
          </div>
        </div>
      )}

      {/* Background Pattern */}
      <div className="absolute inset-0 opacity-5">
        <div className="absolute top-20 left-20 w-32 h-32 rounded-full" style={{ backgroundColor: 'var(--x-white-100)' }}></div>
        <div className="absolute top-60 right-32 w-20 h-20 rounded-full" style={{ backgroundColor: 'var(--x-white-100)' }}></div>
        <div className="absolute bottom-40 left-32 w-16 h-16 rounded-full" style={{ backgroundColor: 'var(--x-white-100)' }}></div>
        <div className="absolute bottom-20 right-20 w-24 h-24 rounded-full" style={{ backgroundColor: 'var(--x-white-100)' }}></div>
      </div>

      {/* Left Side - Virtual Interviewer & Robot */}
      <div className="absolute left-0 top-0 w-3/5 scale-125 h-full flex flex-col items-center justify-center p-8">

        {/* Header */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-full shadow-xl mb-8" style={{ backgroundColor: 'var(--x-purple-200)' }}>
            <svg className="w-10 h-10 text-white" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clipRule="evenodd" />
            </svg>
          </div>
          <h1 className="text-5xl font-bold text-white mb-4 drop-shadow-lg">
            Virtual Interviewer
          </h1>
        </div>

        {/* Animated Robot */}
        <div className="relative mb-8">
          <div className="w-80 h-80 mx-auto  relative">
            <Lottie
              animationData={penguinAnimation}
              loop={true}
              autoplay={true}
              className="w-full h-full drop-shadow-2xl"
              style={{ backgroundColor: '#4a1e47' }}
            />

            {/* Floating Speech Bubbles */}
            <div className="absolute top-[30px] left-0 transform -translate-x-1/2 animate-float-slow">
              <div className="bg-white/95 mb-20 backdrop-blur-sm text-purple-700 px-4 py-3 rounded-2xl text-sm font-medium shadow-xl whitespace-nowrap">
                Hi! Ready for your interview?
              </div>
            </div>

            <div className="absolute bottom-1/4 right-0 transform translate-x-1/2 animate-float-delayed">
              <div className="bg-white/95 backdrop-blur-sm text-green-700 px-4 py-3 rounded-2xl text-sm font-medium shadow-xl whitespace-nowrap">
                All the best!
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Side - Form Card */}
      <div className="absolute right-16 top-1/2 transform -translate-y-1/2 w-[600px]">
        <div className="rounded-3xl shadow-2xl p-6 transform hover:scale-[1.02] transition-all duration-300" style={{ backgroundColor: 'var(--x-white-100)', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)' }}>

          {/* Progress Indicator */}
          <div className="flex items-center justify-center mb-6">
            <div className="flex items-center space-x-4">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all ${currentStep >= 1 ? 'text-white' : 'text-gray-400'
                }`} style={{ backgroundColor: currentStep >= 1 ? 'var(--x-purple-200)' : 'var(--x-white-500)' }}>
                1
              </div>
              <div className="w-16 h-1 rounded-full transition-all" style={{ backgroundColor: currentStep >= 2 ? 'var(--x-purple-200)' : 'var(--x-white-500)' }}></div>
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all ${currentStep >= 2 ? 'text-white' : 'text-gray-400'
                }`} style={{ backgroundColor: currentStep >= 2 ? 'var(--x-purple-200)' : 'var(--x-white-500)' }}>
                2
              </div>
            </div>
          </div>

          {/* Card Header */}
          <div className="text-center mb-4">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl mb-3 shadow-lg" style={{ backgroundColor: 'var(--x-purple-200)' }}>
              {currentStep === 1 ? (
                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              ) : (
                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              )}
            </div>
            <h2 className="text-xl font-bold mb-1" style={{ color: 'var(--x-grey-300)' }}>
              {currentStep === 1 ? 'Personal Details' : 'Take Your Photo'}
            </h2>
            <p className="text-sm" style={{ color: 'var(--x-grey-100)' }}>
              {currentStep === 1 ? 'Enter your information to get started' : 'We\'ll use this for identity verification'}
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-4 p-3 border-l-4 rounded-r-xl animate-fade-in" style={{ backgroundColor: 'var(--x-red-300)', borderColor: 'var(--x-red-200)', color: 'var(--x-red-200)' }}>
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg className="h-5 w-5" style={{ color: 'var(--x-red-200)' }} viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <p className="text-sm">{error}</p>
                </div>
                <button
                  onClick={() => setError(null)}
                  className="ml-auto hover:opacity-80 transition-opacity"
                  style={{ color: 'var(--x-red-200)' }}
                >
                  <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>
          )}

          {/* Step 1: Personal Details */}
          {currentStep === 1 && (
            <div className="space-y-4 animate-fade-in">
              {/* Name Input */}
              <div className="space-y-2">
                <label htmlFor="name" className="block text-sm font-semibold" style={{ color: 'var(--x-grey-300)' }}>
                  Your Name <span style={{ color: 'var(--x-red-200)' }}>*</span>
                </label>
                <input
                  id="name"
                  type="text"
                  placeholder="Enter your full name"
                  value={name}
                  onChange={handleNameChange}
                  required
                  disabled={isLoading}
                  className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 disabled:opacity-50 focus:outline-none"
                  style={{
                    borderColor: 'var(--x-white-500)',
                    backgroundColor: 'var(--x-white-200)',
                    color: 'var(--x-grey-300)'
                  }}
                  onFocus={handleInputFocus}
                  onBlur={handleInputBlur}
                />
              </div>

              {/* Email Input */}
              <div className="space-y-2">
                <label htmlFor="email" className="block text-sm font-semibold" style={{ color: 'var(--x-grey-300)' }}>
                  Your Email
                  <span className="text-sm font-normal ml-2" style={{ color: 'var(--x-grey-100)' }}>(For result notification)</span>
                </label>
                <input
                  id="email"
                  type="email"
                  placeholder="Enter your email address"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isLoading}
                  className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 disabled:opacity-50 focus:outline-none"
                  style={{
                    borderColor: 'var(--x-white-500)',
                    backgroundColor: 'var(--x-white-200)',
                    color: 'var(--x-grey-300)'
                  }}
                  onFocus={handleInputFocus}
                  onBlur={handleInputBlur}
                />
              </div>

              {/* Question Count Selection */}
              <div className="space-y-2">
                <label htmlFor="questionCount" className="block text-sm font-semibold" style={{ color: 'var(--x-grey-300)' }}>
                  Number of Questions <span style={{ color: 'var(--x-red-200)' }}>*</span>
                </label>
                <select
                  id="questionCount"
                  value={questionCount}
                  onChange={handleQuestionCountChange}
                  disabled={isLoading}
                  className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 disabled:opacity-50 focus:outline-none"
                  style={{
                    borderColor: 'var(--x-white-500)',
                    backgroundColor: 'var(--x-white-200)',
                    color: 'var(--x-grey-300)'
                  }}
                  onFocus={handleInputFocus}
                  onBlur={handleInputBlur}
                >
                  {[3, 4, 5, 6, 7, 8].map((num) => (
                    <option key={num} value={num}>
                      {num} Questions
                    </option>
                  ))}
                </select>
                <p className="text-xs" style={{ color: 'var(--x-grey-100)' }}>
                  Select how many questions you'd like to be asked during the interview.
                </p>
              </div>

              {/* Resume Upload */}
              <div className="space-y-2">
                <label htmlFor="resume" className="block text-sm font-semibold" style={{ color: 'var(--x-grey-300)' }}>
                  Upload Your Resume
                  <span className="text-sm font-normal ml-2" style={{ color: 'var(--x-grey-100)' }}>(Optional)</span>
                </label>
                <input
                  id="resume"
                  type="file"
                  accept=".pdf,.doc,.docx,.txt"
                  onChange={handleFileChange}
                  disabled={isLoading}
                  className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:text-white disabled:opacity-50 focus:outline-none"
                  style={{
                    borderColor: 'var(--x-white-500)',
                    backgroundColor: 'var(--x-white-200)',
                    color: 'var(--x-grey-300)'
                  }}
                  onFocus={handleInputFocus}
                  onBlur={handleInputBlur}
                />
                <p className="text-xs" style={{ color: 'var(--x-grey-100)' }}>
                  Supported formats: PDF, DOC, DOCX, TXT. Maximum file size: 10MB.
                </p>
              </div>

              {/* Job Description */}
              <div className="space-y-2">
                <label className="block text-sm font-semibold" style={{ color: 'var(--x-grey-300)' }}>
                  Job Description
                  <span className="text-sm font-normal ml-2" style={{ color: 'var(--x-grey-100)' }}>(Optional)</span>
                </label>

                {/* Toggle tabs */}
                <div className="flex rounded-xl overflow-hidden border-2" style={{ borderColor: 'var(--x-white-500)' }}>
                  <button
                    type="button"
                    onClick={() => setJdInputType('file')}
                    className="flex-1 py-2 text-sm font-medium transition-all duration-200"
                    style={{
                      backgroundColor: jdInputType === 'file' ? 'var(--x-purple-200)' : 'var(--x-white-200)',
                      color: jdInputType === 'file' ? 'white' : 'var(--x-grey-100)'
                    }}
                  >
                    Upload File
                  </button>
                  <button
                    type="button"
                    onClick={() => setJdInputType('text')}
                    className="flex-1 py-2 text-sm font-medium transition-all duration-200"
                    style={{
                      backgroundColor: jdInputType === 'text' ? 'var(--x-purple-200)' : 'var(--x-white-200)',
                      color: jdInputType === 'text' ? 'white' : 'var(--x-grey-100)'
                    }}
                  >
                    Paste Text
                  </button>
                </div>

                {jdInputType === 'file' ? (
                  <>
                    <input
                      id="jd_file"
                      type="file"
                      accept=".txt,.docx"
                      onChange={handleJdFileChange}
                      disabled={isLoading}
                      className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:text-white disabled:opacity-50 focus:outline-none"
                      style={{
                        borderColor: 'var(--x-white-500)',
                        backgroundColor: 'var(--x-white-200)',
                        color: 'var(--x-grey-300)'
                      }}
                    />
                    <p className="text-xs" style={{ color: 'var(--x-grey-100)' }}>
                      Supported formats: TXT, DOCX.
                    </p>
                  </>
                ) : (
                  <textarea
                    placeholder="Paste the job description here..."
                    value={jdText}
                    onChange={(e) => setJdText(e.target.value)}
                    disabled={isLoading}
                    rows={4}
                    className="w-full px-4 py-2 border-2 rounded-xl transition-all duration-200 disabled:opacity-50 focus:outline-none resize-none"
                    style={{
                      borderColor: 'var(--x-white-500)',
                      backgroundColor: 'var(--x-white-200)',
                      color: 'var(--x-grey-300)'
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = 'var(--x-purple-200)'
                      e.currentTarget.style.boxShadow = '0 0 0 2px rgba(230, 161, 219, 0.2)'
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = 'var(--x-white-500)'
                      e.currentTarget.style.boxShadow = 'none'
                    }}
                  />
                )}
              </div>

              {/* Next Button */}
              <button
                type="button"
                onClick={handleNextStep}
                disabled={!name.trim()}
                className="w-full flex items-center justify-center px-6 py-3 text-white font-semibold rounded-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg hover:shadow-xl transform hover:scale-105"
                style={{ backgroundColor: 'var(--x-purple-200)' }}
              >
                Next Step
                <svg className="w-5 h-5 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          )}

          {/* Step 2: Photo Capture */}
          {currentStep === 2 && (
            <div className="space-y-4 animate-fade-in">

              {!showCamera && !capturedImage && (
                <div className="text-center p-6 border-2 border-dashed rounded-xl transition-colors" style={{ borderColor: 'var(--x-white-500)', backgroundColor: 'var(--x-white-200)' }}>
                  <div className="inline-flex items-center justify-center w-12 h-12 rounded-full mb-3" style={{ backgroundColor: 'var(--x-purple-200)' }}>
                    <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  </div>
                  <h3 className="text-base font-medium mb-3" style={{ color: 'var(--x-grey-300)' }}>Ready to capture your photo?</h3>
                  <button
                    type="button"
                    onClick={handleCameraToggle}
                    disabled={isLoading}
                    className="inline-flex items-center px-6 py-3 text-white rounded-xl transition-all duration-200 font-medium shadow-lg hover:shadow-xl disabled:opacity-50 transform hover:scale-105"
                    style={{ backgroundColor: 'var(--x-purple-200)' }}
                  >
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    Access Camera
                  </button>
                </div>
              )}

              {showCamera && (
                <div className="space-y-4">
                  <div className="relative rounded-2xl overflow-hidden shadow-xl" style={{ backgroundColor: 'var(--x-grey-300)' }}>
                    <Webcam
                      ref={webcamRef}
                      audio={false}
                      screenshotFormat="image/jpeg"
                      className="w-full h-auto"
                      style={{ aspectRatio: '4/3', objectFit: 'cover' }}
                      videoConstraints={{
                        width: { ideal: 640 },
                        height: { ideal: 480 },
                        facingMode: 'user'
                      }}
                    />
                    <div className="absolute top-4 left-4 px-3 py-2 rounded-full text-xs font-medium flex items-center" style={{ backgroundColor: 'var(--x-red-200)', color: 'white' }}>
                      <div className="w-2 h-2 bg-white rounded-full mr-2 animate-pulse"></div>
                      Live
                    </div>
                  </div>
                  <div className="flex justify-center space-x-4">
                    <button
                      type="button"
                      onClick={capturePhoto}
                      disabled={isLoading}
                      className="px-6 py-3 text-white rounded-xl transition-all duration-200 font-medium shadow-lg hover:shadow-xl transform hover:scale-105"
                      style={{ backgroundColor: 'var(--x-green-100)' }}
                    >
                      <svg className="w-5 h-5 mr-2 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      Capture
                    </button>
                    <button
                      type="button"
                      onClick={handleCameraToggle}
                      disabled={isLoading}
                      className="px-4 py-3 border-2 rounded-xl transition-all duration-200 font-medium"
                      style={{ borderColor: 'var(--x-white-500)', color: 'var(--x-grey-300)' }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {capturedImage && !showCamera && (
                <div className="space-y-4">
                  <div className="text-center">
                    <div className="inline-block relative">
                      <img
                        src={capturedImage}
                        alt="Captured"
                        className="max-w-full w-full rounded-2xl shadow-xl border-4"
                        style={{ borderColor: 'var(--x-green-100)', maxHeight: '150px', objectFit: 'cover' }}
                      />
                      <div className="absolute top-3 right-3">
                        <div className="px-3 py-2 rounded-full text-xs font-medium flex items-center shadow-lg text-white" style={{ backgroundColor: 'var(--x-green-100)' }}>
                          <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          Ready
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="text-center">
                    <button
                      type="button"
                      onClick={() => { setShowCamera(true); setCapturedImage(null); }}
                      disabled={isLoading}
                      className="px-6 py-2 border-2 rounded-xl transition-all duration-200 text-sm font-medium"
                      style={{ borderColor: 'var(--x-white-500)', color: 'var(--x-grey-300)' }}
                    >
                      Retake Photo
                    </button>
                  </div>
                </div>
              )}

              {/* Navigation Buttons */}
              <div className="flex justify-between pt-4">
                <button
                  type="button"
                  onClick={handlePrevStep}
                  className="flex items-center px-6 py-3 border-2 rounded-xl transition-all duration-200 font-medium"
                  style={{ borderColor: 'var(--x-white-500)', color: 'var(--x-grey-300)' }}
                >
                  <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                  Back
                </button>

                {capturedImage && (
                  <button
                    onClick={startInterview}
                    disabled={isLoading || !name || !capturedImage}
                    className="flex items-center justify-center px-6 py-3 text-white font-semibold rounded-xl transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg hover:shadow-xl transform hover:scale-105"
                    style={{ backgroundColor: 'var(--x-purple-200)' }}
                  >
                    {isLoading ? (
                      <>
                        <svg className="animate-spin w-4 h-4 mr-2 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        Starting...
                      </>
                    ) : (
                      <>
                        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                        </svg>
                        Let's Start
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Custom Styles */}
      <style jsx>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        
        @keyframes float-slow {
          0%, 100% { transform: translateY(0px) translateX(-50%); }
          50% { transform: translateY(-15px) translateX(-50%); }
        }
        
        @keyframes float-delayed {
          0%, 100% { transform: translateY(0px) translateX(50%); }
          50% { transform: translateY(-20px) translateX(50%); }
        }
        
        .animate-fade-in {
          animation: fade-in 0.5s ease-out;
        }
        
        .animate-float-slow {
          animation: float-slow 4s ease-in-out infinite;
        }
        
        .animate-float-delayed {
          animation: float-delayed 4s ease-in-out infinite 2s;
        }

        input[type="file"]::file-selector-button {
          background-color: var(--x-purple-200) !important;
        }

        select {
          appearance: none;
          background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b7280' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
          background-position: right 12px center;
          background-repeat: no-repeat;
          background-size: 16px;
          padding-right: 40px;
        }

        select:focus {
          background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%23e6a1db' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e");
        }
      `}</style>
    </div>
  )
}

export default InterviewHome