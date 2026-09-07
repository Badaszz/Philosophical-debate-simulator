import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { streamDebate, type DebateStream } from "./api/streamDebate";
import type { PhilosopherProfile, TurnEvent } from "./types";

const TOTAL_ROUNDS = 5;

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
  const [topic, setTopic] = useState("");
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [philosophers, setPhilosophers] = useState<PhilosopherProfile[]>([]);
  const [turns, setTurns] = useState<TurnEvent[]>([]);
  const [dialogue, setDialogue] = useState("");
  const [error, setError] = useState("");
  const streamRef = useRef<DebateStream | null>(null);

  const start = async (e: FormEvent) => {
    e.preventDefault();
    if (!topic.trim() || running) return;

    setError("");
    setStatus("Summoning philosophers...");
    setPhilosophers([]);
    setTurns([]);
    setDialogue("");
    setRunning(true);

    const stream = streamDebate(topic.trim(), {
      onPhilosophers: (philosophers) => {
        setPhilosophers(philosophers);
        setStatus("Philosophers ready. Researching sources...");
      },
      onStatus: (message) => setStatus(message),
      onTurn: (turn) => setTurns((prev) => [...prev, turn]),
      onDone: (dialogue) => {
        setDialogue(dialogue);
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

  const showDialogExplorer = Boolean(dialogue);

  return (
    <div className="page">
      <header>
        <h1>Philosophical Debate Simulator</h1>
        <p className="tagline">
          Pit two opposing philosopher personas against each other in a five-round debate,
          live as it unfolds.
        </p>
      </header>

      <form onSubmit={start} className="controls">
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. Is free will compatible with determinism?"
          aria-label="Debate topic"
          readOnly={running}
          autoFocus
        />
        {running ? (
          <button type="button" className="danger" onClick={stop}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!topic.trim()}>
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
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {showDialogExplorer && (
        <details className="dialogue">
          <summary>View full dialogue (plain text)</summary>
          <pre>{dialogue}</pre>
        </details>
      )}

      {philosophers.length > 0 && (
        <section className="grid">
          {philosophers.map((p) => (
            <PhilosopherCard key={p.name} philosopher={p} />
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
          {turns.map((turn, i) => (
            <TurnBlock
              key={`${turn.round}-${turn.speaker}`}
              turn={turn}
              previousSpeaker={i > 0 ? turns[i - 1].speaker : null}
            />
          ))}
        </section>
      )}
    </div>
  );
}