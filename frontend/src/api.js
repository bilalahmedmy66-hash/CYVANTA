const API_ROOT = `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1`;

export function getSession() {
  try {
    const raw = sessionStorage.getItem("cyvanta.session");
    if (!raw) return null;
    const session = JSON.parse(raw);
    if (!session?.accessToken || !session?.expiresAt) return null;
    if (Date.now() >= session.expiresAt) {
      sessionStorage.removeItem("cyvanta.session");
      return null;
    }
    return session;
  } catch {
    sessionStorage.removeItem("cyvanta.session");
    return null;
  }
}

export function saveSession(tokenResponse, profile, organizations = [], preferredOrganizationId = null) {
  const memberships = Array.isArray(organizations) ? organizations : [];
  const selected = memberships.find((item) =>
    String(item.organization_id) === String(preferredOrganizationId)
  ) || memberships[0] || null;

  const session = {
    accessToken: tokenResponse.access_token,
    expiresAt: Date.now() + (Number(tokenResponse.expires_in) * 1000),
    profile,
    organizations: memberships,
    organizationId: selected?.organization_id ?? null,
    organizationName: selected?.organization_name ?? null,
    organizationRole: selected?.role ?? null,
  };
  sessionStorage.setItem("cyvanta.session", JSON.stringify(session));
  return session;
}

export function clearSession() {
  sessionStorage.removeItem("cyvanta.session");
}

export async function apiRequest(path, options = {}) {
  const session = getSession();
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");

  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (session?.accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${session.accessToken}`);
  }
  if (session?.organizationId && !headers.has("X-Organization-ID")) {
    headers.set("X-Organization-ID", session.organizationId);
  }

  const response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null
      ? payload.detail || payload.message
      : payload;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function loadOrganizations(accessToken) {
  const response = await fetch(`${API_ROOT}/auth/organizations`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null
      ? payload.detail || payload.message
      : payload;
    const error = new Error(detail || `Organization lookup failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return Array.isArray(payload) ? payload : [];
}

export async function authenticate(email, password) {
  const token = await apiRequest("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  const headers = { Authorization: `Bearer ${token.access_token}` };
  const profile = await apiRequest("/auth/me", { headers });
  const organizations = await loadOrganizations(token.access_token);
  return saveSession(token, profile, organizations);
}

export async function registerAccount(email, password, organizationName) {
  await apiRequest("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      organization_name: organizationName,
    }),
  });
  return authenticate(email, password);
}

export async function acceptOrganizationInvitation(invitationToken) {
  const session = getSession();
  if (!session?.accessToken) {
    throw new Error("Sign in with the invited email address before accepting this invitation.");
  }

  const accepted = await apiRequest("/organizations/invitations/accept", {
    method: "POST",
    body: JSON.stringify({ token: invitationToken }),
  });

  const organizations = await loadOrganizations(session.accessToken);
  const refreshed = saveSession(
    {
      access_token: session.accessToken,
      expires_in: Math.max(1, Math.floor((session.expiresAt - Date.now()) / 1000)),
    },
    session.profile,
    organizations,
    accepted.organization_id
  );

  return { ...accepted, session: refreshed };
}
export async function verifySession() {
  const session = getSession();
  if (!session) return null;
  try {
    const headers = { Authorization: `Bearer ${session.accessToken}` };
    const profile = await apiRequest("/auth/me", { headers });
    const organizations = await loadOrganizations(session.accessToken);
    return saveSession(
      { access_token: session.accessToken, expires_in: Math.max(1, Math.floor((session.expiresAt - Date.now()) / 1000)) },
      profile,
      organizations,
      session.organizationId
    );
  } catch (error) {
    if (error.status === 401) clearSession();
    throw error;
  }
}