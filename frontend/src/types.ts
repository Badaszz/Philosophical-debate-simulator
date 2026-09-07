export interface PhilosopherProfile {
  name: string;
  school: string;
  stance: string;
  core_claims: string[];
  argumentative_style: string;
  primary_goal: string;
}

export interface TurnEvent {
  round: number;
  speaker: string;
  argument: string;
  question: string;
}

export type StreamEventName =
  | "philosophers"
  | "status"
  | "turn"
  | "done"
  | "error";