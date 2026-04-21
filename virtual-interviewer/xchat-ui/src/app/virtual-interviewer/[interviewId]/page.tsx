import  InterviewSession  from '../_components/InterviewSession'

interface InterviewSessionPageProps {
  params: {
    interviewId: string
  }
}

export default function InterviewSessionPage({ params }: InterviewSessionPageProps) {
  return <InterviewSession interviewId={params.interviewId} />
}