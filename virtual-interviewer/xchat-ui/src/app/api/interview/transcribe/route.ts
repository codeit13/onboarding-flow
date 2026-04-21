// app/api/interview/transcribe/route.ts
import { type NextRequest } from "next/server";

const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;

export async function POST(request: NextRequest) {
    const backendUrl = `${REAL_API_BASE_URL}/interview/transcribe`;
    try {
        const body = await request.json();
        const backendResponse = await fetch(backendUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
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