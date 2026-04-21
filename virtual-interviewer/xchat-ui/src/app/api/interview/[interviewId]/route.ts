// app/api/interview/[interviewId]/route.ts
const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(
    request: Request,
    { params }: { params: { interviewId: string } }
) {
    const { interviewId } = params;
    const backendUrl = `${REAL_API_BASE_URL}/interview/${interviewId}`;
    try {
        const backendResponse = await fetch(backendUrl, {
            cache: "no-store",
            headers: {
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        });
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
