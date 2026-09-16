import { cache } from "react";
import { apiFetch } from "@/lib/api";
import type { User } from "@/lib/types";

/**
 * GET /users/me for server components. `cache` dedupes it within one request,
 * so the app layout and a page both asking for it costs one round trip.
 */
export const fetchCurrentUser = cache((): Promise<User> => apiFetch<User>("/users/me"));
