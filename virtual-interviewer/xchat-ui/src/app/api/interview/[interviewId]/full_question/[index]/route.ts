// app/api/interview/[interviewId]/full_question/[index]/route.ts
const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;

export async function GET(
    request: Request,
    { params }: { params: { interviewId: string; index: string } }
) {
    const { interviewId, index } = params;
    const backendUrl = `${REAL_API_BASE_URL}/interview/${interviewId}/full_question/${index}`;
    try {
        const backendResponse = await fetch(backendUrl);
        return new Response(backendResponse.body, {
            status: backendResponse.status,
            statusText: backendResponse.statusText,
            headers: backendResponse.headers,
        });
    } catch (error) {
        console.error(`[API PROXY] Error fetching ${backendUrl}:`, error);
        return new Response(
            JSON.stringify({ message: "Error connecting to the backend service." }),
            { status: 502, headers: { "Content-Type": "application/json" } }
        );
    }
}