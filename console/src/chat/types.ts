// UI port. The HTTP adapter validates AR-1 wire DTOs separately.
export type Mode = "chat" | "agent";
export type RunState =
  | "accepted"
  | "running"
  | "waiting_approval"
  | "needs_confirmation"
  | "completed"
  | "cancelled"
  | "failed"
  | "limit_reached";
export interface Message {
  id: string;
  role: "user" | "assistant" | "tool";
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
export interface Approval {
  id: string;
  callId: string;
  tool: string;
  revision: string;
  argsHash: string;
  policyRevision: string;
  expiresAt: string;
  state: string;
  input: string;
}
export interface UsageGroup {
  currency: string;
  price_version: string;
  known_tokens: string;
  held_tokens: string;
  inflight_tokens: string;
  known_money_atomic: string;
  held_money_atomic: string;
  inflight_money_atomic: string;
}
export interface Run {
  id: string;
  commandId: string;
  mode: Mode;
  model: string;
  state: RunState;
  assistantId: string;
  cursor: number | string;
  sequence?: string;
  cancelRequested?: boolean;
  childRequestIds?: string[];
  aggregationComplete?: boolean;
  usageGroups?: UsageGroup[];
  approvals?: Approval[];
  steps: Step[];
  usage: { tokens: number | string | null; reason: string | null };
  error?: string;
}
export interface Session {
  id: string;
  title: string;
  updatedAt: string;
  messages: Message[];
  runs: Run[];
  revision?: string;
  activeRunId?: string | null;
}
export interface ChatEvent {
  seq: number | string;
  runId: string;
  type:
    | "sync"
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
  operation?: "send" | "edit" | "regenerate";
}
export interface ChatService {
  models(): Promise<{ id: string; label: string; modes: Mode[] }[]>;
  list(): Promise<Session[]>;
  create(model?: string): Promise<Session>;
  rename(id: string, title: string): Promise<void>;
  remove(id: string): Promise<void>;
  read(id: string): Promise<Session>;
  start(input: StartInput): Promise<Run>;
  events(
    sessionId: string,
    runId: string,
    after: number | string,
  ): Promise<EventPage>;
  cancel(sessionId: string, runId: string): Promise<void>;
  approve(
    sessionId: string,
    runId: string,
    callId: string,
    allow: boolean,
  ): Promise<void>;
  clear(): Promise<void>;
  recover?(): Promise<Session | null>;
  hasPending?(): boolean;
  stopEvents?(): void;
  dispose?(): void;
}
