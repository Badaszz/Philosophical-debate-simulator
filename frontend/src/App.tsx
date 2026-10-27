import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiRequest, type AdminState, type UserProfile } from "./api/authApi";
import { streamDebate, type CooldownEvent, type DebateStream } from "./api/streamDebate";
import { supabase } from "./auth/supabase";
import type { Session } from "@supabase/supabase-js";
import type { PhilosopherProfile, TurnEvent } from "./types";

const TOTAL_ROUNDS = 5;

function formatRemaining(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatUtcReset(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

function PhilosopherCard({ philosopher }: { philosopher: PhilosopherProfile }) {
  return (
    <article className="card">
      <h3>{philosopher.name}</h3>
      <p className="school">{philosopher.school}</p>
      <p className="stance">{philosopher.stance}</p>
      <p className="style">{philosopher.argumentative_style}</p>
      <ul className="claims">
        {philosopher.core_claims.map((claim, i) => (
          <li key={i}>{claim}</li>
        ))}
      </ul>
      <p className="goal">
        <strong>Goal:</strong> {philosopher.primary_goal}
      </p>
    </article>
  );
}

function TurnBlock({ turn, previousSpeaker }: { turn: TurnEvent; previousSpeaker: string | null }) {
  const isNewSpeaker = turn.speaker !== previousSpeaker;
  return (
    <article className={isNewSpeaker ? "turn" : "turn reply"}>
      <div className="turn-head">
        <span className="speaker">@{turn.speaker}</span>
        <span className="round">Round {turn.round}</span>
      </div>
      <p>{turn.argument}</p>
      <p className="question">
        <strong>Question:</strong> {turn.question}
      </p>
    </article>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [adminState, setAdminState] = useState<AdminState | null>(null);
  const [topic, setTopic] = useState("");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [philosophers, setPhilosophers] = useState<PhilosopherProfile[]>([]);
  const [turns, setTurns] = useState<TurnEvent[]>([]);
  const [dialogue, setDialogue] = useState("");
  const [error, setError] = useState("");
  const [authError, setAuthError] = useState("");
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [newAllowedEmail, setNewAllowedEmail] = useState("");
  const [adminBusy, setAdminBusy] = useState(false);
  const streamRef = useRef<DebateStream | null>(null);

  useEffect(() => {
    if (!supabase) {
      setAuthError("Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY to enable sign-in.");
      setAuthReady(true);
      return;
    }

    const callbackError =
      new URLSearchParams(window.location.search).get("error_description") ??
      new URLSearchParams(window.location.hash.slice(1)).get("error_description");
    if (callbackError) {
      setAuthError(callbackError);
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, nextSession) => {
      setSession(nextSession);
      setAuthReady(true);
      if (event === "SIGNED_IN") setAuthError("");
    });

    void supabase.auth
      .getSession()
      .then(({ data, error: sessionError }) => {
        if (sessionError) setAuthError(sessionError.message);
        setSession(data.session);
        setAuthReady(true);
      })
      .catch((cause: unknown) => {
        setAuthError(cause instanceof Error ? cause.message : "Could not restore your sign-in.");
        setAuthReady(true);
      });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) {
      setProfile(null);
      setAdminState(null);
      setCooldownUntil(null);
      setSecondsLeft(0);
      return;
    }

    let active = true;
    setProfile(null);
    void apiRequest<UserProfile>("/auth/me", session.access_token)
      .then((result) => {
        if (!active) return;
        setProfile(result);
        if (result.remaining_seconds > 0) {
          setCooldownUntil(
            result.available_at
              ? Date.parse(result.available_at)
              : Date.now() + result.remaining_seconds * 1000,
          );
        } else {
          setCooldownUntil(null);
        }
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setAuthError(
          cause instanceof Error ? cause.message : "Could not verify this account.",
        );
      });

    return () => {
      active = false;
    };
  }, [session?.access_token]);

  useEffect(() => {
    if (!profile?.is_admin || !session) {
      setAdminState(null);
      return;
    }

    let active = true;
    void apiRequest<AdminState>("/admin/state", session.access_token)
      .then((state) => {
        if (active) setAdminState(state);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Could not load admin settings.");
        }
      });

    return () => {
      active = false;
    };
  }, [profile?.is_admin, session?.access_token]);

  useEffect(() => {
    if (!session || !profile?.daily_reset_at) return;

    const resetDelay = Math.max(
      0,
      Date.parse(profile.daily_reset_at) - Date.now() + 100,
    );
    const timer = window.setTimeout(() => {
      void apiRequest<UserProfile>("/auth/me", session.access_token)
        .then(setProfile)
        .catch((cause: unknown) => {
          setError(cause instanceof Error ? cause.message : "Could not refresh daily usage.");
        });
    }, resetDelay);

    return () => window.clearTimeout(timer);
  }, [profile?.daily_reset_at, session?.access_token]);

  useEffect(() => {
    if (cooldownUntil === null) {
      setSecondsLeft(0);
      return;
    }

    const updateRemaining = () => {
      const remaining = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
      setSecondsLeft(remaining);
      if (remaining === 0) setCooldownUntil(null);
    };
    updateRemaining();
    const timer = window.setInterval(updateRemaining, 1000);
    return () => window.clearInterval(timer);
  }, [cooldownUntil]);

  const start = async (e: FormEvent) => {
    e.preventDefault();
    if (!topic.trim() || running || !session) return;
    if (!profile?.rate_limit_exempt && secondsLeft > 0) return;

    setError("");
    setStatus("Summoning philosophers...");
    setPhilosophers([]);
    setTurns([]);
    setDialogue("");
    setRunning(true);

    const stream = streamDebate(topic.trim(), session.access_token, {
      onPhilosophers: (nextPhilosophers) => {
        setPhilosophers(nextPhilosophers);
        setStatus("Philosophers ready. Researching sources...");
      },
      onStatus: (message) => setStatus(message),
      onCooldown: (usage: CooldownEvent) => {
        setProfile((current) =>
          current
            ? {
                ...current,
                total_requests: usage.total_requests,
                daily_request_count: usage.daily_request_count,
                daily_limit: usage.daily_limit,
                daily_remaining: usage.daily_remaining,
                daily_reset_at: usage.daily_reset_at ?? current.daily_reset_at,
                remaining_seconds: usage.remaining_seconds,
                available_at: usage.available_at,
              }
            : current,
        );
        if (
          !profile?.rate_limit_exempt &&
          usage.limit_reason !== "daily_limit" &&
          usage.remaining_seconds > 0
        ) {
          setCooldownUntil(
            usage.available_at
              ? Date.parse(usage.available_at)
              : Date.now() + usage.remaining_seconds * 1000,
          );
        }
      },
      onTurn: (turn) => setTurns((previous) => [...previous, turn]),
      onDone: (nextDialogue) => {
        setDialogue(nextDialogue);
        setStatus("Debate complete.");
        setRunning(false);
      },
      onError: (message) => {
        setError(message);
        setStatus("");
        setRunning(false);
      },
    });

    streamRef.current = stream;
    await stream.finished;
    streamRef.current = null;
  };

  const stop = () => {
    streamRef.current?.cancel();
    streamRef.current = null;
    setStatus("Cancelled.");
    setRunning(false);
  };

  const signIn = async () => {
    if (!supabase) return;
    setAuthError("");
    try {
      const { error: signInError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.origin },
      });
      if (signInError) setAuthError(signInError.message);
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "Google sign-in failed.");
    }
  };

  const signOut = async () => {
    if (!supabase) return;
    try {
      const { error: signOutError } = await supabase.auth.signOut();
      if (signOutError) setError(signOutError.message);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-out failed.");
    }
  };

  const reloadAdminState = async () => {
    if (!session) return;
    const state = await apiRequest<AdminState>("/admin/state", session.access_token);
    setAdminState(state);
  };

  const addAllowedUser = async (event: FormEvent) => {
    event.preventDefault();
    if (!session || !newAllowedEmail.trim()) return;
    setAdminBusy(true);
    setError("");
    try {
      await apiRequest<void>("/admin/allowed-users", session.access_token, {
        method: "POST",
        body: JSON.stringify({ email: newAllowedEmail }),
      });
      setNewAllowedEmail("");
      await reloadAdminState();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add that email.");
    } finally {
      setAdminBusy(false);
    }
  };

  const removeAllowedUser = async (email: string) => {
    if (!session) return;
    setAdminBusy(true);
    setError("");
    try {
      await apiRequest<void>("/admin/allowed-users", session.access_token, {
        method: "DELETE",
        body: JSON.stringify({ email }),
      });
      await reloadAdminState();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not remove that email.");
    } finally {
      setAdminBusy(false);
    }
  };

  const setRestriction = async (enabled: boolean) => {
    if (!session) return;
    setAdminBusy(true);
    setError("");
    try {
      const state = await apiRequest<AdminState>("/admin/settings", session.access_token, {
        method: "PUT",
        body: JSON.stringify({ restrict_sign_in: enabled }),
      });
      setAdminState(state);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update sign-in access.");
    } finally {
      setAdminBusy(false);
    }
  };

  const remainingLabel = formatRemaining(secondsLeft);
  const showDialogExplorer = Boolean(dialogue);

  if (!authReady) {
    return <main className="page"><p className="status">Checking your sign-in...</p></main>;
  }

  if (!session) {
    return (
      <main className="page auth-page">
        <header>
          <h1>Philosophical Debate Simulator</h1>
          <p className="tagline">Sign in with Google to start a debate.</p>
        </header>
        {authError && <div className="error" role="alert">{authError}</div>}
        <button className="google-button" type="button" onClick={() => void signIn()} disabled={!supabase}>
          Continue with Google
        </button>
      </main>
    );
  }

  if (!profile) {
    return (
      <main className="page">
        {authError ? (
          <>
            <div className="error" role="alert">{authError}</div>
            <button type="button" onClick={() => void signOut()}>Sign out</button>
          </>
        ) : (
          <p className="status">Checking account access...</p>
        )}
      </main>
    );
  }

  const cooldownActive = !profile.rate_limit_exempt && secondsLeft > 0;
  const dailyLimitReached =
    !profile.rate_limit_exempt && profile.daily_remaining <= 0;

  return (
    <main className="page">
      <header className="app-header">
        <div>
          <h1>Philosophical Debate Simulator</h1>
          <p className="tagline">
            Pit two opposing philosopher personas against each other in a five-round debate,
            live as it unfolds.
          </p>
        </div>
        <div className="account">
          <span>{profile.email}</span>
          <button type="button" className="secondary-button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>

      {profile.rate_limit_exempt ? (
        <p className="rate-limit exempt" role="status">
          {profile.daily_request_count} debate{profile.daily_request_count === 1 ? "" : "s"} made
          today (UTC). No cooldown or daily limit applies to this account.
        </p>
      ) : (
        <div className="rate-limit" role="status" aria-live="polite">
          <p>
            {profile.daily_request_count}/{profile.daily_limit} debates used today (UTC);
            {" "}{profile.daily_remaining} remaining.
            {" "}{dailyLimitReached && profile.daily_reset_at
              ? `Daily limit resets at ${formatUtcReset(profile.daily_reset_at)}.`
              : `Daily allowance resets at ${formatUtcReset(profile.daily_reset_at)}.`}
          </p>
          <p>
            {cooldownActive
              ? `Next debate available in ${remainingLabel}.`
              : "One debate is available now; after starting, wait 10 minutes before the next."}
          </p>
        </div>
      )}
      <p className="rate-limit-note">Debate topics are limited to 100 tokens.</p>

      {profile.is_admin && adminState && (
        <section className="admin-panel">
          <h2>Admin settings</h2>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={adminState.restrict_sign_in}
              disabled={adminBusy}
              onChange={(event) => void setRestriction(event.target.checked)}
            />
            Restrict sign-in to allowed users
          </label>
          <p className="admin-help">
            When enabled, only the administrator and emails below can use the app. New
            sign-ups are blocked and existing non-allowed accounts lose API access.
            Allowed users are exempt from the 10-minute cooldown.
          </p>
          <form className="admin-add" onSubmit={(event) => void addAllowedUser(event)}>
            <input
              type="email"
              value={newAllowedEmail}
              onChange={(event) => setNewAllowedEmail(event.target.value)}
              placeholder="person@example.com"
              aria-label="Email to allow"
              required
            />
            <button type="submit" disabled={adminBusy}>Add user</button>
          </form>
          <ul className="allowed-users">
            {adminState.allowed_users.map((email) => (
              <li key={email}>
                <span>{email}</span>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={adminBusy || email === profile.email}
                  onClick={() => void removeAllowedUser(email)}
                >
                  Remove
                </button>
              </li>
            ))}
            {adminState.allowed_users.length === 0 && <li>No additional users are allowed.</li>}
          </ul>
        </section>
      )}

      <form onSubmit={start} className="controls">
        <input
          type="text"
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="e.g. Is free will compatible with determinism?"
          aria-label="Debate topic"
          maxLength={10000}
          readOnly={running}
          autoFocus
        />
        {running ? (
          <button type="button" className="danger" onClick={stop}>Stop</button>
        ) : (
          <button
            type="submit"
            disabled={!topic.trim() || cooldownActive || dailyLimitReached}
          >
            Start Debate
          </button>
        )}
      </form>

      {running && (
        <div className="status" role="status">
          <span className="spinner" />
          {status || "Working..."}
        </div>
      )}
      {error && <div className="error" role="alert">{error}</div>}
      {showDialogExplorer && (
        <details className="dialogue">
          <summary>View full dialogue (plain text)</summary>
          <pre>{dialogue}</pre>
        </details>
      )}

      {philosophers.length > 0 && (
        <section className="grid">
          {philosophers.map((philosopher) => (
            <PhilosopherCard key={philosopher.name} philosopher={philosopher} />
          ))}
        </section>
      )}

      {turns.length > 0 && (
        <section className="transcript">
          <h2>
            Transcript
            <span className="progress">
              {Math.min(Math.max(turns.length / 2, 0), TOTAL_ROUNDS)}/{TOTAL_ROUNDS} rounds
            </span>
          </h2>
          {turns.map((turn, index) => (
            <TurnBlock
              key={`${turn.round}-${turn.speaker}`}
              turn={turn}
              previousSpeaker={index > 0 ? turns[index - 1].speaker : null}
            />
          ))}
        </section>
      )}
      <footer className="site-footer">
        <p>
          Made by Badasz ·{" "}
          <a href="https://badasz-portfolio.vercel.app" target="_blank" rel="noopener noreferrer">
            badasz-portfolio.vercel.app
          </a>
        </p>
        <p className="privacy-disclaimer">
          Debate topics are sent to our configured LLM provider to generate the debate; we do not
          save them in this app.
        </p>
      </footer>
    </main>
  );
}
