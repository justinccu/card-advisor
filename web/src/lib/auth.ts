"use client";

// Who is signed in, in one of two modes fixed at build time:
//  - "dev" (`make demo`): a local user id in localStorage, sent as X-Dev-User; the local API
//    accepts it only when APP_ENV=local.
//  - "cognito" (`make web-aws`, and any deployed build): Cognito via Amplify Auth. Sign-in uses
//    SRP, so the password never leaves the page; the API receives the access token, which API
//    Gateway verifies before the app sees the request.
import { Amplify } from "aws-amplify";
import {
  confirmSignUp as amplifyConfirmSignUp,
  deleteUser,
  fetchAuthSession,
  getCurrentUser,
  resendSignUpCode as amplifyResendSignUpCode,
  signIn as amplifySignIn,
  signOut as amplifySignOut,
  signUp as amplifySignUp,
} from "aws-amplify/auth";

import { SESSION_KEY, readSession, writeSession } from "./session";

const POOL_ID = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID;
const CLIENT_ID = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;

export const AUTH_MODE: "dev" | "cognito" = POOL_ID && CLIENT_ID ? "cognito" : "dev";
export const AUTH_EVENT = "card-advisor:session";

let configured = false;
function configure(): void {
  if (configured || AUTH_MODE !== "cognito") return;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: POOL_ID!,
        userPoolClientId: CLIENT_ID!,
        loginWith: { email: true },
        signUpVerificationMethod: "code",
      },
    },
  });
  configured = true;
}

function changed(): void {
  window.dispatchEvent(new Event(AUTH_EVENT));
}

/** The signed-in user's id (Cognito `sub`, or the dev id), or null. */
export async function currentUserId(): Promise<string | null> {
  if (AUTH_MODE === "dev") return readSession();
  configure();
  try {
    return (await getCurrentUser()).userId;
  } catch {
    return null; // no session, or the refresh token expired
  }
}

/** Headers that identify the caller to the API (refreshes the access token when needed). */
export async function authHeaders(): Promise<Record<string, string>> {
  if (AUTH_MODE === "dev") {
    const uid = readSession();
    return uid ? { "X-Dev-User": uid } : {};
  }
  configure();
  try {
    const token = (await fetchAuthSession()).tokens?.accessToken?.toString();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

export async function signOut(): Promise<void> {
  if (AUTH_MODE === "dev") writeSession(null);
  else {
    configure();
    await amplifySignOut().catch(() => undefined); // local sign-out even if offline
  }
  changed();
}

// --- dev mode ---------------------------------------------------------------------------

export function devSignIn(uid: string): void {
  writeSession(uid);
}

// --- cognito mode -----------------------------------------------------------------------

export type SignUpStep = "confirm" | "done";

/** Invite-only: the code rides along to the pre sign-up trigger as client metadata. */
export async function signUp(email: string, password: string, inviteCode: string): Promise<SignUpStep> {
  configure();
  const { nextStep } = await amplifySignUp({
    username: email,
    password,
    options: { userAttributes: { email }, clientMetadata: { invite_code: inviteCode } },
  });
  return nextStep.signUpStep === "CONFIRM_SIGN_UP" ? "confirm" : "done";
}

export async function confirmSignUp(email: string, code: string): Promise<void> {
  configure();
  await amplifyConfirmSignUp({ username: email, confirmationCode: code.trim() });
}

export async function resendSignUpCode(email: string): Promise<void> {
  configure();
  await amplifyResendSignUpCode({ username: email });
}

export type SignInResult = "signed-in" | "confirm-email";

export async function signIn(email: string, password: string): Promise<SignInResult> {
  configure();
  // A stale session (e.g. another account in this browser) would make signIn throw.
  await amplifySignOut().catch(() => undefined);
  const { isSignedIn, nextStep } = await amplifySignIn({ username: email, password });
  if (!isSignedIn && nextStep.signInStep === "CONFIRM_SIGN_UP") return "confirm-email";
  changed();
  return "signed-in";
}

/** Deletes the Cognito account itself (after the API has purged the user's data). */
export async function deleteAccount(): Promise<void> {
  if (AUTH_MODE === "dev") return signOut();
  configure();
  await deleteUser();
  changed();
}

/** Readable text for Cognito errors (the pre sign-up trigger's message included). */
export function authErrorMessage(err: unknown): string {
  const e = err as { name?: string; message?: string };
  switch (e?.name) {
    case "UserLambdaValidationException":
      return "That invite code is invalid or has been used up.";
    case "UsernameExistsException":
      return "An account with this email already exists. Sign in instead.";
    case "InvalidPasswordException":
      return "Use at least 12 characters with upper- and lowercase letters and a number.";
    case "CodeMismatchException":
      return "That code doesn’t match. Check the latest email we sent.";
    case "ExpiredCodeException":
      return "That code has expired. Send a new one.";
    case "NotAuthorizedException":
      return "Incorrect email or password.";
    case "LimitExceededException":
    case "TooManyRequestsException":
      return "Too many attempts. Wait a minute and try again.";
    default:
      return e?.message || "Something went wrong.";
  }
}

export { SESSION_KEY };
