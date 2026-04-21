"use client";

/**
 * External candidate status page.
 *
 * Mirrors the internal Thrive status experience exactly — same slot
 * confirmation flow, same R1 launch button, same activity feed — by
 * delegating to the existing /thrive/status/[appId] page via client
 * redirect. This keeps the external flow byte-for-byte identical to
 * the internal flow without forking 1,100 lines of UI code.
 *
 * Why client-side redirect (and not a Next.js redirect()): the demo
 * URL bar should reflect that the candidate is in the EXTERNAL flow
 * for the brief moment between intake → status, then we hand off to
 * the shared status page so the funnel UI is identical.
 */

import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export default function ExternalStatusRedirect() {
  const router = useRouter();
  const params = useParams<{ appId: string }>();

  useEffect(() => {
    if (params?.appId) {
      router.replace(`/thrive/status/${params.appId}`);
    }
  }, [params?.appId, router]);

  return (
    <main className="min-h-screen bg-axis-surface flex items-center justify-center">
      <p className="text-sm text-axis-muted">Loading your application…</p>
    </main>
  );
}
