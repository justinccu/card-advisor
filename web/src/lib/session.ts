// Local demo session (the dev user id). On AWS this is replaced by Cognito tokens.
export const SESSION_KEY = "card-advisor.uid";

export function readSession(): string | null {
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null; // private mode / blocked storage: behave as signed out
  }
}

export function writeSession(uid: string | null): void {
  try {
    if (uid === null) window.localStorage.removeItem(SESSION_KEY);
    else window.localStorage.setItem(SESSION_KEY, uid);
  } catch {
    /* storage unavailable: session lasts only for this page view */
  }
  window.dispatchEvent(new Event("card-advisor:session"));
}

// This device's Advisor conversation, per user (lib/advisor). Kept here, with no imports, so
// sign-out (lib/auth) can clear it without importing the Advisor.
export const ADVISOR_STORE_PREFIX = "card-advisor.advisor.";

/** On sign-out: no one else on this device sees the conversation. */
export function clearAdvisorConversations(): void {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith(ADVISOR_STORE_PREFIX)) window.localStorage.removeItem(key);
    }
  } catch {
    /* nothing stored */
  }
}
