import { NextRequest, NextResponse } from "next/server";

const REAL_API_BASE_URL = `${process.env.MIDDLEWARE_URL}/api`;

export async function GET(request: NextRequest) {
    const returnUrl = request.nextUrl.searchParams.get("return_url");
    const backendUrl = new URL(`${REAL_API_BASE_URL}/interview/google-auth/connect`);

    if (returnUrl) {
        backendUrl.searchParams.set("return_url", returnUrl);
    }

    return NextResponse.redirect(backendUrl.toString());
}
