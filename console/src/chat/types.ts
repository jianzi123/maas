// UI development port; shared MAAS-2/20 wire protocol is pending. No production routes implied.
export type Mode = "chat" | "agent";
export type RunState =
  "running" | "waiting_approval" | "completed" | "cancelled" | "failed";
export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  runId?: string;
  requestId?: string;
  replaces?: string;
  createdAt: string;
}
export interface Step {
  id: string;
  label: string;
  state: string;
  input?: string;
  output?: string;
  callId?: string;
}
export interface Run {
  id: string;
  commandId: string;
  mode: Mode;
  model: string;
  state: RunState;
  assistantId: string;
  cursor: number;
  steps: Step[];
  usage: { tokens: number | null; reason: string | null };
  error?: string;
}
export interface Session {
  id: string;
  title: string;
  updatedAt: string;
  messages: Message[];
  runs: Run[];
}
export interface ChatEvent {
  seq: number;
  runId: string;
  type:
    | "delta"
    | "step"
    | "approval"
    | "usage"
    | "completed"
    | "failed"
    | "cancelled";
  text?: string;
  step?: Step;
  tokens?: number | null;
}
export interface EventPage {
  events: ChatEvent[];
  snapshot: Session;
}
export interface StartInput {
  commandId: string;
  sessionId: string;
  content: string;
  model: string;
  mode: Mode;
  replaces?: string;
}
export interface ChatService {
  models(): Promise<{ id: string; label: string; modes: Mode[] }[]>;
  list(): Promise<Session[]>;
  create(): Promise<Session>;
  rename(id: string, title: string): Promise<void>;
  remove(id: string): Promise<void>;
  read(id: string): Promise<Session>;
  start(input: StartInput): Promise<Run>;
  events(sessionId: string, runId: string, after: number): Promise<EventPage>;
  cancel(sessionId: string, runId: string): Promise<void>;
  approve(
    sessionId: string,
    runId: string,
    callId: string,
    allow: boolean,
  ): Promise<void>;
  clear(): Promise<void>;
}
