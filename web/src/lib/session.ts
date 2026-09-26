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
