// app/api/interview/start/route.ts
import { type NextRequest } from "next/server";

const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;

export async function POST(request: NextRequest) {
    const backendUrl = `${REAL_API_BASE_URL}/interview/start`;

    try {
        const headers = new Headers(request.headers);
        headers.delete("host");

        const backendResponse = await fetch(backendUrl, {
            method: "POST",
            headers,
            body: request.body,
            duplex: "half",
        } as RequestInit); // <-- This is the fix

        return new Response(backendResponse.body, {
            status: backendResponse.status,
            statusText: backendResponse.statusText,
            headers: backendResponse.headers,
        });
    } catch (error) {
        console.error(`[API PROXY] Error fetching ${backendUrl}:`, error);
        return new Response(
            JSON.stringify({ message: "Error connecting to the backend service." }),
            {
                status: 502, // Bad Gateway
                headers: { "Content-Type": "application/json" },
            }
        );
    }
}