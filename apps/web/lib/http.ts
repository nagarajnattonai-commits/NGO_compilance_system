export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function apiRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method, credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Setu-Request": "1" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ApiError("Cannot connect to the server. Please try again.", 0);
  }
  if (!response.ok) {
    let message = response.status >= 500 ? "The server is unavailable. Please try again shortly." : `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join(", ");
    } catch { /* An upstream failure may return HTML, not JSON. */ }
    if (response.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") window.location.assign("/login?expired=1");
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
