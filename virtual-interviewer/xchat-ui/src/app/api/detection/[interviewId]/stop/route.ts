// app/api/detection/[interviewId]/stop/route.ts
const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;

export async function POST(
    request: Request,
    { params }: { params: { interviewId: string } }
) {
    const { interviewId } = params;
    const backendUrl = `${REAL_API_BASE_URL}/detection/${interviewId}/stop`;
    try {
        const backendResponse = await fetch(backendUrl, { method: "POST" });
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