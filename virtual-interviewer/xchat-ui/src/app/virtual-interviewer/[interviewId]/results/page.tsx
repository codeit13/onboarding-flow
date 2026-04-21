// app/virtual-interviewer/[interviewId]/results/page.tsx

import InterviewResults from '../../_components/InterviewResults'

interface ResultsPageProps {
  params: {
    interviewId: string
  }
}

export default function ResultsPage({ params }: ResultsPageProps) {
  return <InterviewResults interviewId={params.interviewId} />
}