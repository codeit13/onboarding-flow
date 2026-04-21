'use client'

import React, { useState, useEffect } from 'react'
import axios, { AxiosError } from 'axios'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

// API Configuration

// --- TypeScript Interfaces ---
interface Question {
  id: number | string
  question: string
  answer: string | null
}

// Raw data structure from the API for real-time metrics
interface RealTimeMetricsFromAPI {
  emotionalState?: {
    confidence?: number
    primaryEmotion?: string
    emotionBreakdown?: Record<string, number | string>
  }
  posture?: {
    confidence?: number
    status?: string
    issues?: string[]
  }
  eyeTracking?: {
    confidence?: number
    gazeStability?: number
    suspiciousMovements?: boolean
    direction?: string
    status?: string
  }
  cheatingDetection?: {
    confidence?: number
    suspiciousActivities?: string[]
    riskLevel?: 'low' | 'medium' | 'high' | string
  }
  overallConfidenceScore?: number
}

// Raw data structure for evaluation from the API
interface EvaluationDataFromAPI {
  'Overall assessment'?: string
  'Strengths identified'?: string[]
  'Areas for improvement'?: string[]
  'Technical skills assessment'?: string
  'Communication skills assessment'?: string
  'Final recommendation'?: string
  'Real time analysis'?: RealTimeMetricsFromAPI
}

// Raw data structure for the entire interview from the API
interface InterviewDataFromAPI {
  id: string
  name?: string
  start_time?: string
  questions: Question[]
  evaluation: EvaluationDataFromAPI | null
  metadata?: {
    selected_for_next_round?: boolean
    selection_email_sent?: boolean
    selection_email_sent_at?: string
  }
}

// Interface for formatted real-time metrics for display
interface DisplayRealTimeMetrics {
  'Overall Confidence Score'?: string
  'Emotional State Analysis'?: {
    Confidence?: string
    'Primary Emotion'?: string
    'Emotion Breakdown'?: { emotion: string; value: string }[]
  }
  'Posture Analysis'?: {
    Confidence?: string
    Status?: string
    issues?: string[]
  }
  'Eye Movement Analysis'?: {
    Confidence?: string
    'Gaze Stability'?: string
    Status?: string
    Direction?: string
  }
  'Integrity Analysis'?: {
    Confidence?: string
    'Suspicious Activities'?: string[]
    'Risk Level'?: string
  }
}

// Main data structure for the report page, containing formatted display data
interface ReportDisplayData {
  interview_id: string
  candidate_name: string
  interview_date: string
  transcript: Question[]
  evaluationSection: EvaluationDataFromAPI | null
  displayRealTimeMetrics: DisplayRealTimeMetrics | null
  metadata?: InterviewDataFromAPI['metadata']
}

interface InterviewResultsProps {
  interviewId: string
}

interface GoogleAuthStatus {
  connected: boolean
  calendar_id?: string
  interviewer_email?: string
}

// Fixed helper function to format numbers to percentage strings
const formatToPercentageString = (
  value: number | string | undefined,
  decimalPlaces: number = 1
): string => {
  if (value === undefined || value === null || String(value).trim() === '') return 'N/A'

  let num: number

  if (typeof value === 'string') {
    // Remove % sign if present and parse
    const cleanValue = value.toString().replace('%', '').trim()
    num = parseFloat(cleanValue)
  } else {
    num = value
  }

  if (isNaN(num)) return 'N/A'

  // Ensure the number is within 0-100 range
  num = Math.min(Math.max(num, 0), 100)

  return `${num.toFixed(decimalPlaces)}%`
}

const SELECTED_KEYWORDS = ['select', 'hire', 'recommend', 'proceed', 'offer', 'congratul', 'advance']
const REJECT_KEYWORDS = ['not recommend', 'not hire', 'reject', 'do not hire', 'not select', 'not suitable', 'not proceed']

const isCandidateSelected = (
  evaluation: EvaluationDataFromAPI | null,
  metadata?: InterviewDataFromAPI['metadata']
): boolean => {
  if (metadata?.selected_for_next_round) {
    return true
  }

  const finalRecommendation = evaluation?.['Final recommendation']?.toLowerCase() || ''
  return (
    SELECTED_KEYWORDS.some(keyword => finalRecommendation.includes(keyword)) &&
    !REJECT_KEYWORDS.some(keyword => finalRecommendation.includes(keyword))
  )
}

const InterviewResults: React.FC<InterviewResultsProps> = ({ interviewId }) => {
  const searchParams = useSearchParams()
  const [reportData, setReportData] = useState<ReportDisplayData | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [isEvaluating, setIsEvaluating] = useState<boolean>(false)
  const [retryCount, setRetryCount] = useState<number>(0)
  const [selectedSlot, setSelectedSlot] = useState<string>('')
  const [isScheduling, setIsScheduling] = useState<boolean>(false)
  const [scheduleSuccess, setScheduleSuccess] = useState<{
    meetLink: string
    slot: string
  } | null>(null)
  const [googleAuthStatus, setGoogleAuthStatus] = useState<GoogleAuthStatus | null>(null)
  const [currentUrl, setCurrentUrl] = useState<string>('')

  const MAX_RETRIES = 2
  const RETRY_DELAY = 3000

  const mapApiDataToDisplayData = (apiInterviewData: InterviewDataFromAPI): ReportDisplayData => {
    let displayRTM: DisplayRealTimeMetrics | null = null
    const rtmRaw = apiInterviewData.evaluation?.['Real time analysis']

    if (rtmRaw) {
      displayRTM = {
        'Overall Confidence Score': formatToPercentageString(rtmRaw.overallConfidenceScore, 2),
        'Emotional State Analysis': rtmRaw.emotionalState ? {
          'Primary Emotion': rtmRaw.emotionalState.primaryEmotion || 'N/A',
          Confidence: formatToPercentageString(rtmRaw.emotionalState.confidence),
          'Emotion Breakdown': rtmRaw.emotionalState.emotionBreakdown ?
            Object.entries(rtmRaw.emotionalState.emotionBreakdown).map(([key, val]) => ({
              emotion: key.charAt(0).toUpperCase() + key.slice(1),
              value: formatToPercentageString(val)
            })) : [],
        } : undefined,
        'Posture Analysis': rtmRaw.posture ? {
          Status: rtmRaw.posture.status || 'N/A',
          Confidence: formatToPercentageString(rtmRaw.posture.confidence),
          issues: rtmRaw.posture.issues || [],
        } : undefined,
        'Eye Movement Analysis': rtmRaw.eyeTracking ? {
          Direction: rtmRaw.eyeTracking.direction || 'N/A',
          'Gaze Stability': formatToPercentageString(rtmRaw.eyeTracking.gazeStability),
          Confidence: formatToPercentageString(rtmRaw.eyeTracking.confidence),
          Status: rtmRaw.eyeTracking.suspiciousMovements ? 'Suspicious Movement Detected' : (rtmRaw.eyeTracking.status || 'Normal'),
        } : undefined,
        'Integrity Analysis': rtmRaw.cheatingDetection ? {
          'Risk Level': rtmRaw.cheatingDetection.riskLevel?.toUpperCase() || 'N/A',
          Confidence: formatToPercentageString(rtmRaw.cheatingDetection.confidence),
          'Suspicious Activities': rtmRaw.cheatingDetection.suspiciousActivities || [],
        } : undefined,
      }
    }

    return {
      interview_id: apiInterviewData.id,
      candidate_name: apiInterviewData.name || 'N/A',
      interview_date: apiInterviewData.start_time
        ? new Date(apiInterviewData.start_time).toLocaleString()
        : 'N/A',
      transcript: Array.isArray(apiInterviewData.questions)
        ? apiInterviewData.questions.map(q => ({
          id: q.id,
          question: q.question || 'N/A',
          answer: q.answer || null
        }))
        : [],
      evaluationSection: apiInterviewData.evaluation,
      displayRealTimeMetrics: displayRTM,
      metadata: apiInterviewData.metadata,
    }
  }

  const fetchInterviewData = async () => {
    if (!interviewId) {
      setError('Interview ID is required')
      setIsLoading(false)
      return
    }

    console.log(`Fetching interview data for ID: ${interviewId}, Attempt: ${retryCount + 1}`)
    setIsLoading(true)
    setError(null)

    try {
      const response = await axios.get<{
        success: boolean
        interview: InterviewDataFromAPI
        message?: string
      }>(
        `/api/interview/${interviewId}`,
        { timeout: 15000 }
      )

      console.log("API Response for GET /api/interview:", response.data)

      if (response.data.success && response.data.interview) {
        const mappedData = mapApiDataToDisplayData(response.data.interview)
        setReportData(mappedData)
        setRetryCount(0)
      } else {
        const errorMsg = response.data.message || 'Failed to load interview results. Invalid data structure received.'
        setError(errorMsg)
        if (retryCount < MAX_RETRIES) {
          setTimeout(() => setRetryCount(prev => prev + 1), RETRY_DELAY)
        }
      }
    } catch (err) {
      const axiosError = err as AxiosError<{ message?: string; detail?: any }>
      console.error('Error fetching interview:', axiosError)

      let errorMessage = 'An error occurred while loading interview results.'

      if (axiosError.response) {
        const status = axiosError.response.status
        const responseData = axiosError.response.data

        if (status === 404) {
          errorMessage = `Interview with ID ${interviewId} not found.`
        } else if (status === 500) {
          errorMessage = 'Server error occurred. Please try again later.'
        } else {
          errorMessage = `Error ${status}: ${responseData?.message || axiosError.response.statusText}`
        }
      } else if (axiosError.request) {
        errorMessage = 'No response received from server. Check network connection.'
      } else {
        errorMessage = axiosError.message || 'Unknown error occurred'
      }

      setError(errorMessage)

      // Only retry if it's not a 404 and we haven't exceeded max retries
      if (axiosError.response?.status !== 404 && retryCount < MAX_RETRIES) {
        setTimeout(() => setRetryCount(prev => prev + 1), RETRY_DELAY)
      }
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchInterviewData()
  }, [interviewId, retryCount])

  useEffect(() => {
    const url = new URL(window.location.href)
    url.searchParams.delete('google_auth')
    url.searchParams.delete('message')
    setCurrentUrl(url.toString())
  }, [])

  useEffect(() => {
    const fetchGoogleAuthStatus = async () => {
      try {
        const response = await axios.get<{
          success: boolean
          status: GoogleAuthStatus
        }>(`/api/interview/google-auth/status`, { timeout: 15000 })

        if (response.data.success) {
          setGoogleAuthStatus(response.data.status)
        }
      } catch (err) {
        console.error('Error fetching Google auth status:', err)
      }
    }

    fetchGoogleAuthStatus()
  }, [])

  useEffect(() => {
    const authState = searchParams.get('google_auth')
    const authMessage = searchParams.get('message')

    if (authState === 'success') {
      setGoogleAuthStatus(prev => ({ ...(prev || {}), connected: true }))
      const cleanUrl = new URL(window.location.href)
      cleanUrl.searchParams.delete('google_auth')
      cleanUrl.searchParams.delete('message')
      window.history.replaceState({}, '', cleanUrl.toString())
    } else if (authState === 'error' && authMessage) {
      setError(decodeURIComponent(authMessage))
      const cleanUrl = new URL(window.location.href)
      cleanUrl.searchParams.delete('google_auth')
      cleanUrl.searchParams.delete('message')
      window.history.replaceState({}, '', cleanUrl.toString())
    }
  }, [searchParams])

  const generateEvaluation = async () => {
    if (!interviewId || !reportData) return

    setIsEvaluating(true)
    setError(null)

    try {
      console.log(`Requesting evaluation for interview: ${interviewId}`)
      const response = await axios.post<{
        success: boolean
        evaluation: EvaluationDataFromAPI
        message?: string
      }>(
        `/api/interview/${interviewId}/evaluate`,
        {},
        { timeout: 90000 }
      )

      console.log("API Response for POST /evaluate:", response.data)

      if (response.data.success && response.data.evaluation) {
        setReportData(prev => {
          if (!prev) return null
          const updatedApiInterviewData: InterviewDataFromAPI = {
            id: prev.interview_id,
            name: prev.candidate_name,
            start_time: prev.interview_date,
            questions: prev.transcript,
            evaluation: response.data.evaluation,
            metadata: prev.metadata,
          }
          return mapApiDataToDisplayData(updatedApiInterviewData)
        })
        await fetchInterviewData()
      } else {
        setError(response.data.message || 'Failed to generate evaluation. Please try again.')
      }
    } catch (err) {
      const axiosError = err as AxiosError<{ message?: string }>
      console.error('Error generating evaluation:', axiosError)

      let errorMessage = 'An error occurred while generating evaluation.'

      if (axiosError.response) {
        errorMessage = `Error ${axiosError.response.status}: ${axiosError.response.data?.message || 'Failed to generate evaluation'
          }`
      } else if (axiosError.code === 'ECONNABORTED') {
        errorMessage = 'Evaluation request timed out. Please try again.'
      } else {
        errorMessage = axiosError.message || 'Unknown error occurred during evaluation'
      }

      setError(errorMessage)
    } finally {
      setIsEvaluating(false)
    }
  }

  const scheduleMeet = async () => {
    if (!interviewId || !selectedSlot) {
      setError('Please choose a date and time before clicking Done.')
      return
    }
    if (!googleAuthStatus?.connected) {
      setError('Connect Google Calendar before scheduling the Meet link.')
      return
    }

    setIsScheduling(true)
    setError(null)

    try {
      const response = await axios.post<{
        success: boolean
        meet_link: string
        slot: string
        email_sent: boolean
        message?: string
      }>(`/api/interview/${interviewId}/schedule-meet`, { slot: selectedSlot }, { timeout: 30000 })

      if (response.data.success) {
        setScheduleSuccess({
          meetLink: response.data.meet_link,
          slot: response.data.slot,
        })
      } else {
        setError(response.data.message || 'Failed to schedule the Google Meet link.')
      }
    } catch (err) {
      const axiosError = err as AxiosError<{ message?: string; detail?: string }>
      const responseData = axiosError.response?.data
      setError(
        responseData?.detail ||
        responseData?.message ||
        axiosError.message ||
        'Unable to schedule the interview slot right now.'
      )
    } finally {
      setIsScheduling(false)
    }
  }

  // Helper functions for styling
  const getRiskLevelTailwind = (level?: string) => {
    switch (level?.toLowerCase()) {
      case 'low': return 'bg-green-100 text-green-800'
      case 'medium': return 'bg-yellow-100 text-yellow-800'
      case 'high': return 'bg-red-100 text-red-800'
      default: return 'bg-gray-100 text-gray-800'
    }
  }

  const getEyeStatusTailwind = (status?: string) => {
    if (!status) return 'bg-gray-100 text-gray-800'
    return status.toLowerCase().includes('suspicious')
      ? 'bg-yellow-100 text-yellow-800'
      : 'bg-green-100 text-green-800'
  }

  // Loading state
  if (isLoading && retryCount === 0) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
        <div className="text-center">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-slate-100 rounded-full mb-6" style={{ backgroundColor: '#f8fafc' }}>
            <svg className="animate-spin w-10 h-10" style={{ color: '#4a1e47' }} xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Loading Interview Results...</h2>
          <p className="text-gray-600">Please wait while we compile your interview data.</p>
        </div>
      </div>
    )
  }

  // Error state without data
  if (error && !reportData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
        <div className="max-w-md mx-auto w-full">
          <div className="bg-white rounded-2xl shadow-xl p-8 text-center" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
            <div className="inline-flex items-center justify-center w-16 h-16 bg-red-100 rounded-full mb-4">
              <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">Failed to Load Results</h2>
            <p className="text-gray-600 mb-6">{error}</p>
            <div className="flex flex-col sm:flex-row justify-center space-y-3 sm:space-y-0 sm:space-x-3">
              {retryCount < MAX_RETRIES && !error.includes("not found") && (
                <button
                  onClick={() => fetchInterviewData()}
                  className="w-full sm:w-auto px-6 py-3 text-white rounded-xl hover:opacity-90 focus:ring-2 focus:ring-offset-2 transition-colors duration-200 font-medium focus:ring-purple-500"
                  style={{ backgroundColor: '#4a1e47' }}
                >
                  Try Again ({MAX_RETRIES - retryCount} left)
                </button>
              )}
              <Link href="/virtual-interviewer" passHref legacyBehavior>
                <a className="w-full sm:w-auto block px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 transition-colors duration-200 font-medium text-center">
                  Back to Home
                </a>
              </Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Safe destructuring with null check
  if (!reportData) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center p-4">
        <div className="max-w-md mx-auto w-full">
          <div className="bg-white rounded-2xl shadow-xl p-8 text-center" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
            <div className="inline-flex items-center justify-center w-16 h-16 bg-yellow-100 rounded-full mb-4">
              <svg className="w-8 h-8 text-yellow-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">No Data Available</h2>
            <p className="text-gray-600 mb-6">Unable to load interview results.</p>
            <Link href="/virtual-interviewer" passHref legacyBehavior>
              <a className="px-6 py-3 text-white rounded-xl hover:opacity-90 focus:ring-2 focus:ring-offset-2 transition-colors duration-200 font-medium focus:ring-purple-500" style={{ backgroundColor: '#4a1e47' }}>
                Back to Home
              </a>
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const { transcript, evaluationSection, displayRealTimeMetrics } = reportData
  const candidateSelected = isCandidateSelected(evaluationSection, reportData.metadata)

  const overallConfidenceScoreValue = displayRealTimeMetrics?.['Overall Confidence Score']
    ? parseFloat(displayRealTimeMetrics['Overall Confidence Score'].replace('%', ''))
    : 0

  return (
    <div className="bg-gradient-to-br from-slate-50 max-h-screen overflow-y-auto to-slate-100 min-h-screen pb-10">
      <div className="max-w-6xl mx-auto px-4 py-8 ">
        {/* Header */}
        <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
          <div className="p-8" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
            <div className="text-center text-white">
              <div className="inline-flex items-center justify-center w-16 h-16 bg-white/20 rounded-full mb-4">
                <svg className="w-8 h-8" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              </div>
              <h1 className="text-4xl font-bold mb-2">Interview Results</h1>
              <p className="text-white/80">
                Candidate: {reportData.candidate_name} • Date: {reportData.interview_date}
              </p>
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && reportData && (
          <div className="mb-6 p-4 bg-yellow-50 border-l-4 border-yellow-400 text-yellow-700 rounded-r-lg">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-yellow-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <p>{error}</p>
              </div>
            </div>
          </div>
        )}

        {/* Interview Transcript */}
        <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
          <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
            <h2 className="text-2xl font-bold text-white">Interview Transcript</h2>
          </div>
          <div className="p-8">
            {transcript && transcript.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-16">#</th>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Question</th>
                      <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Answer</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {transcript.map((item, index) => (
                      <tr key={item.id || index}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{index + 1}</td>
                        <td className="px-6 py-4 text-sm text-gray-700 break-words">{item.question}</td>
                        <td className="px-6 py-4 text-sm text-gray-700 break-words">
                          {item.answer || <em className="text-gray-400">No answer provided</em>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-12">
                <svg className="w-16 h-16 text-gray-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <p className="text-gray-500">No transcript data available.</p>
              </div>
            )}
          </div>
        </div>

        {/* Evaluation Section */}
        {!evaluationSection ? (
          <div className="bg-white rounded-2xl shadow-xl overflow-hidden p-8 text-center mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
            <h2 className="text-2xl font-bold text-gray-900 mb-4">Interview Evaluation</h2>
            <p className="text-gray-600 mb-6">Generate an evaluation to get feedback on performance.</p>
            <button
              onClick={generateEvaluation}
              disabled={isEvaluating}
              className="inline-flex items-center px-8 py-4 text-white text-lg font-semibold rounded-xl hover:opacity-90 focus:ring-2 focus:ring-offset-2 transition-all duration-200 shadow-lg disabled:opacity-70 disabled:cursor-not-allowed focus:ring-purple-500"
              style={{
                background: isEvaluating ? '#6a2c5a' : 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)'
              }}
            >
              {isEvaluating ? (
                <>
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Generating...
                </>
              ) : (
                'Generate Evaluation'
              )}
            </button>
          </div>
        ) : (
          <>
            {/* Overall Assessment */}
            <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
              <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
                <h2 className="text-2xl font-bold text-white">Overall Assessment</h2>
              </div>
              <div className="p-8">
                <p className="text-gray-800 text-lg leading-relaxed">
                  {evaluationSection['Overall assessment'] || <em className="text-gray-400">N/A</em>}
                </p>
              </div>
            </div>

            {/* Strengths and Areas for Improvement */}
            <div className="grid md:grid-cols-2 gap-8 mb-8">
              <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-green-200">
                <div className="bg-gradient-to-r from-green-500 to-green-600 p-6">
                  <h3 className="text-xl font-bold text-white">Strengths</h3>
                </div>
                <div className="p-6">
                  {(evaluationSection['Strengths identified'] && evaluationSection['Strengths identified']!.length > 0) ? (
                    <ul className="space-y-3">
                      {evaluationSection['Strengths identified']!.map((item, idx) => (
                        <li key={idx} className="flex items-start">
                          <svg className="w-5 h-5 text-green-500 mr-3 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                          </svg>
                          <span className="text-gray-700">{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-gray-500">N/A</p>
                  )}
                </div>
              </div>

              <div className="bg-white rounded-2xl shadow-xl overflow-hidden border border-yellow-200">
                <div className="bg-gradient-to-r from-yellow-500 to-yellow-600 p-6">
                  <h3 className="text-xl font-bold text-white">Areas for Improvement</h3>
                </div>
                <div className="p-6">
                  {(evaluationSection['Areas for improvement'] && evaluationSection['Areas for improvement']!.length > 0) ? (
                    <ul className="space-y-3">
                      {evaluationSection['Areas for improvement']!.map((item, idx) => (
                        <li key={idx} className="flex items-start">
                          <svg className="w-5 h-5 text-yellow-500 mr-3 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                          </svg>
                          <span className="text-gray-700">{item}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-gray-500">N/A</p>
                  )}
                </div>
              </div>
            </div>

            {/* Technical and Communication Skills */}
            <div className="grid md:grid-cols-2 gap-8 mb-8">
              <div className="bg-white rounded-2xl shadow-xl overflow-hidden" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
                <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
                  <h3 className="text-xl font-bold text-white">Technical Skills</h3>
                </div>
                <div className="p-6">
                  <p className="text-gray-700 leading-relaxed">
                    {evaluationSection['Technical skills assessment'] || <em className="text-gray-400">N/A</em>}
                  </p>
                </div>
              </div>

              <div className="bg-white rounded-2xl shadow-xl overflow-hidden" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
                <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
                  <h3 className="text-xl font-bold text-white">Communication Skills</h3>
                </div>
                <div className="p-6">
                  <p className="text-gray-700 leading-relaxed">
                    {evaluationSection['Communication skills assessment'] || <em className="text-gray-400">N/A</em>}
                  </p>
                </div>
              </div>
            </div>

            {/* Final Recommendation */}
            <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
              <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
                <h2 className="text-2xl font-bold text-white">Final Recommendation</h2>
              </div>
            <div className="p-8">
                <p className="text-gray-800 text-lg leading-relaxed">
                  {evaluationSection['Final recommendation'] || <em className="text-gray-400">N/A</em>}
                </p>
              </div>
            </div>

            {candidateSelected && (
              <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
                <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
                  <h2 className="text-2xl font-bold text-white">Choose Your Interview Slot</h2>
                </div>
                <div className="p-8">
                  {!scheduleSuccess && (
                    <div className="space-y-5">
                      {!googleAuthStatus?.connected && (
                        <div className="rounded-xl border border-blue-200 bg-blue-50 p-5 text-blue-900">
                          <p className="text-lg font-semibold">Connect Google Calendar</p>
                          <p className="mt-2 text-sm">
                            You need to connect the interviewer Google account once before the app can create Meet links.
                          </p>
                          <a
                            href={`/api/interview/google-auth/connect?return_url=${encodeURIComponent(currentUrl || `/virtual-interviewer/${interviewId}/results`)}`}
                            className="mt-4 inline-flex items-center rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-700"
                          >
                            Connect Google Calendar
                          </a>
                        </div>
                      )}

                      <div>
                        <label htmlFor="slot-picker" className="mb-2 block text-sm font-semibold text-gray-700">
                          Preferred date and time
                        </label>
                        <input
                          id="slot-picker"
                          type="datetime-local"
                          value={selectedSlot}
                          min={new Date().toISOString().slice(0, 16)}
                          onChange={(event) => setSelectedSlot(event.target.value)}
                          className="w-full rounded-xl border border-gray-300 px-4 py-3 text-gray-900 outline-none transition focus:border-transparent focus:ring-2 focus:ring-purple-500"
                        />
                      </div>

                      <button
                        onClick={scheduleMeet}
                        disabled={isScheduling || !selectedSlot || !googleAuthStatus?.connected}
                        className="inline-flex items-center px-8 py-4 text-white text-lg font-semibold rounded-xl hover:opacity-90 focus:ring-2 focus:ring-offset-2 transition-all duration-200 shadow-lg disabled:opacity-70 disabled:cursor-not-allowed focus:ring-purple-500"
                        style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}
                      >
                        {isScheduling ? 'Sending Meet Link...' : 'Done'}
                      </button>
                    </div>
                  )}

                  {scheduleSuccess && (
                    <div className="rounded-xl border border-green-200 bg-green-50 p-5 text-green-900">
                      <p className="text-lg font-semibold">Your slot is confirmed.</p>
                      <p className="mt-2">
                        A Google Meet link has been sent to your email for <span className="font-medium">{scheduleSuccess.slot}</span>.
                      </p>
                      <p className="mt-2 text-sm break-all">
                        Meet link: {scheduleSuccess.meetLink}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {/* Real-Time Analysis */}
        {displayRealTimeMetrics && (
          <div className="bg-white rounded-2xl shadow-xl overflow-hidden mb-8" style={{ borderColor: '#4a1e47', borderWidth: '1px' }}>
            <div className="p-6" style={{ background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)' }}>
              <h2 className="text-2xl font-bold text-white">Real-Time Interview Analysis</h2>
            </div>
            <div className="p-8">
              {/* Overall Confidence Score */}
              <div className="mb-8 p-6 rounded-xl border" style={{ backgroundColor: '#faf9fb', borderColor: '#4a1e47' }}>
                <h3 className="text-lg font-semibold mb-4 text-center" style={{ color: '#4a1e47' }}>Overall Confidence Score</h3>
                <div className="relative">
                  <div className="w-full bg-slate-200 rounded-full h-6 overflow-hidden">
                    <div
                      className="h-6 rounded-full transition-all duration-500 flex items-center justify-end pr-2 relative"
                      style={{
                        width: `${Math.min(Math.max(overallConfidenceScoreValue, 0), 100)}%`,
                        background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)'
                      }}
                    >
                      {overallConfidenceScoreValue > 5 && (
                        <span className="text-white text-sm font-medium whitespace-nowrap">
                          {displayRealTimeMetrics['Overall Confidence Score']}
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Display score outside the bar if it's very low */}
                  {overallConfidenceScoreValue <= 5 && (
                    <div className="absolute right-0 top-0 h-6 flex items-center pl-2">
                      <span className="text-gray-700 text-sm font-medium">
                        {displayRealTimeMetrics['Overall Confidence Score']}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Analysis Grid */}
              <div className="grid md:grid-cols-2 gap-6">
                {/* Eye Movement Analysis */}
                {displayRealTimeMetrics['Eye Movement Analysis'] && (
                  <div className="bg-gray-50 rounded-xl p-6 border border-gray-200">
                    <h4 className="font-semibold text-gray-900 mb-4 flex items-center">
                      <svg className="w-5 h-5 mr-2 flex-shrink-0" style={{ color: '#4a1e47' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      </svg>
                      Eye Movement
                    </h4>
                    <div className="space-y-3 text-sm">
                      <div><span className="font-medium text-gray-700">Direction:</span> <span className="text-gray-600">{displayRealTimeMetrics['Eye Movement Analysis'].Direction}</span></div>
                      <div><span className="font-medium text-gray-700">Gaze Stability:</span> <span className="text-gray-600">{displayRealTimeMetrics['Eye Movement Analysis']['Gaze Stability']}</span></div>
                      <div><span className="font-medium text-gray-700">Confidence:</span> <span className="text-gray-600">{displayRealTimeMetrics['Eye Movement Analysis'].Confidence}</span></div>
                      <div>
                        <span className="font-medium text-gray-700">Status:</span>
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ml-1 ${getEyeStatusTailwind(displayRealTimeMetrics['Eye Movement Analysis'].Status)}`}>
                          {displayRealTimeMetrics['Eye Movement Analysis'].Status}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Integrity Analysis */}
                {displayRealTimeMetrics['Integrity Analysis'] && (
                  <div className="bg-gray-50 rounded-xl p-6 border border-gray-200">
                    <h4 className="font-semibold text-gray-900 mb-4 flex items-center">
                      <svg className="w-5 h-5 mr-2 flex-shrink-0" style={{ color: '#4a1e47' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </svg>
                      Integrity
                    </h4>
                    <div className="space-y-3 text-sm">
                      <div>
                        <span className="font-medium text-gray-700">Risk Level:</span>
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ml-1 ${getRiskLevelTailwind(displayRealTimeMetrics['Integrity Analysis']['Risk Level'])}`}>
                          {displayRealTimeMetrics['Integrity Analysis']['Risk Level']}
                        </span>
                      </div>
                      <div><span className="font-medium text-gray-700">Confidence:</span> <span className="text-gray-600">{displayRealTimeMetrics['Integrity Analysis'].Confidence}</span></div>
                      {(displayRealTimeMetrics['Integrity Analysis']['Suspicious Activities'] && displayRealTimeMetrics['Integrity Analysis']['Suspicious Activities']!.length > 0) && (
                        <div>
                          <span className="font-medium text-gray-700 block">Detected Issues:</span>
                          <ul className="list-disc list-inside">
                            {displayRealTimeMetrics['Integrity Analysis']['Suspicious Activities']!.map((activity: string, idx: number) => (
                              <li key={idx} className="text-red-600">{activity}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Posture Analysis */}
                {displayRealTimeMetrics['Posture Analysis'] && (
                  <div className="bg-gray-50 rounded-xl p-6 border border-gray-200">
                    <h4 className="font-semibold text-gray-900 mb-4 flex items-center">
                      <svg className="w-5 h-5 mr-2 flex-shrink-0" style={{ color: '#4a1e47' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      Posture
                    </h4>
                    <div className="space-y-3 text-sm">
                      <div><span className="font-medium text-gray-700">Current Posture:</span> <span className="text-gray-600">{displayRealTimeMetrics['Posture Analysis'].Status}</span></div>
                      <div><span className="font-medium text-gray-700">Confidence:</span> <span className="text-gray-600">{displayRealTimeMetrics['Posture Analysis'].Confidence}</span></div>
                      {(displayRealTimeMetrics['Posture Analysis'].issues && displayRealTimeMetrics['Posture Analysis'].issues!.length > 0) && (
                        <div>
                          <span className="font-medium text-gray-700 block">Issues Detected:</span>
                          <ul className="list-disc list-inside">
                            {displayRealTimeMetrics['Posture Analysis'].issues!.map((issue: string, idx: number) => (
                              <li key={idx} className="text-yellow-600">{issue}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Emotional State Analysis */}
                {displayRealTimeMetrics['Emotional State Analysis'] && (
                  <div className="bg-gray-50 rounded-xl p-6 border border-gray-200">
                    <h4 className="font-semibold text-gray-900 mb-4 flex items-center">
                      <svg className="w-5 h-5 mr-2 flex-shrink-0" style={{ color: '#4a1e47' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      Emotional State
                    </h4>
                    <div className="space-y-3 text-sm">
                      <div><span className="font-medium text-gray-700">Primary Emotion:</span> <span className="text-gray-600">{displayRealTimeMetrics['Emotional State Analysis']['Primary Emotion']}</span></div>
                      <div><span className="font-medium text-gray-700">Confidence:</span> <span className="text-gray-600">{displayRealTimeMetrics['Emotional State Analysis'].Confidence}</span></div>
                      {(displayRealTimeMetrics['Emotional State Analysis']['Emotion Breakdown'] && displayRealTimeMetrics['Emotional State Analysis']['Emotion Breakdown']!.length > 0) && (
                        <div>
                          <span className="font-medium text-gray-700 block mb-1">Emotion Breakdown:</span>
                          <div className="space-y-0.5">
                            {displayRealTimeMetrics['Emotional State Analysis']['Emotion Breakdown']!.map((item: { emotion: string; value: string }) => (
                              <div key={item.emotion} className="flex justify-between text-xs">
                                <span className="text-gray-600">{item.emotion}:</span>
                                <span className="text-gray-800 font-medium">{item.value}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Back to Home Button */}
        <div className="text-center pb-8">
          <Link href="/virtual-interviewer" passHref legacyBehavior>
            <a className="inline-flex items-center px-8 py-4 text-white text-lg font-semibold rounded-xl hover:opacity-90 focus:ring-2 focus:ring-offset-2 transition-all duration-200 shadow-lg focus:ring-purple-500" style={{
              background: 'linear-gradient(135deg, #4a1e47 0%, #6a2c5a 100%)'
            }}>
              <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
              </svg>
              Start New Interview
            </a>
          </Link>
        </div>
      </div>
    </div>
  )
}

export default InterviewResults
