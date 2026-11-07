import type { NextRequest } from "next/server";

export const runtime = "nodejs";

const upstreamOrigin = "https://localhost:8443";
const hopByHopHeaders = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

async function proxy(request: NextRequest): Promise<Response> {
  if (process.env.NODE_ENV !== "development") {
    return new Response("Not found", { status: 404 });
  }

  const incoming = new URL(request.url);
  const upstream = new URL(`${incoming.pathname}${incoming.search}`, upstreamOrigin);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");

  // The backend accepts account mutations only from the Caddy public origin.
  // Map only this same-origin local frontend request; cross-origin requests keep
  // their original Origin and are rejected by the backend's exact-origin check.
  if (headers.get("origin") === incoming.origin) {
    headers.set("origin", upstreamOrigin);
  }

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch {
    return Response.json({ detail: "Local API proxy could not reach https://localhost:8443" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  upstreamResponse.headers.forEach((value, name) => {
    if (!hopByHopHeaders.has(name.toLowerCase()) && name.toLowerCase() !== "set-cookie") {
      responseHeaders.append(name, value);
    }
  });
  for (const cookie of upstreamResponse.headers.getSetCookie()) {
    responseHeaders.append("set-cookie", cookie);
  }

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
