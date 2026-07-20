export type UserProfile = {
  id: string | null;
  name: string;
  goal: string;
  training_days: string[];
  session_minutes: number;
  equipment: string | null;
  experience_level: string | null;
};

export type SessionExercise = {
  name: string;
  target_sets?: number;
  target_reps?: string;
  suggested_reps?: string;
  suggested_weight?: number;
  suggested_rest?: number;
  note?: string;
  is_circuit?: boolean;
  circuit_rounds?: number;
  circuit_position?: number;
  circuit_size?: number;
};

export type SessionPlan = {
  date: string;
  today_day: string;
  is_rest_day: boolean;
  next_training_day?: string | null;
  day_name?: string;
  session_id?: string;
  exercises: SessionExercise[];
  override?: {
    target_date: string;
    scope: string;
    reason?: string | null;
  } | null;
};

export type LoggedSet = {
  id: number;
  session_id?: string | null;
  exercise: string;
  sets: number;
  reps: number;
  weight_kg: number;
  rpe?: number | null;
  notes?: string | null;
};

export type TodaySets = {
  date: string;
  sets: LoggedSet[];
};

export type ProgressionSuggestion = {
  exercise: string;
  next_weight: number;
  next_sets?: number;
  next_reps?: string;
  reason?: string;
  basis?: string;
};

export type FinishSessionResponse = {
  session_id: string;
  evaluation: string;
  suggestions: ProgressionSuggestion[];
  idempotent?: boolean;
};

export type AgentResponse = {
  message: string;
  actions: unknown[];
  requires_confirmation: boolean;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type ApiClientOptions = {
  baseUrl: string;
  token: string;
};

export class HeraclesApi {
  private baseUrl: string;
  private token: string;

  constructor({ baseUrl, token }: ApiClientOptions) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.token = token;
  }

  async me(): Promise<UserProfile> {
    return this.request('/api/v1/me');
  }

  async plan(): Promise<SessionPlan> {
    return this.request('/api/v1/session/plan');
  }

  async today(): Promise<TodaySets> {
    return this.request('/api/v1/session/today');
  }

  async logSet(payload: {
    session_id: string;
    exercise: string;
    reps: number;
    weight_kg: number;
    rpe?: number | null;
    notes?: string;
  }): Promise<LoggedSet> {
    return this.request('/api/v1/session/sets', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async finishSession(sessionId: string): Promise<FinishSessionResponse> {
    const idempotencyKey = `${sessionId}:${Date.now()}`;
    return this.request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/finish`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
    });
  }

  async sendAgentMessage(message: string): Promise<AgentResponse> {
    return this.request('/api/v1/agent/messages', {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        message = body.detail || message;
      } catch {
        // Keep the default HTTP message.
      }
      throw new ApiError(response.status, message);
    }

    return response.json();
  }
}

export const DEFAULT_API_URL =
  process.env.EXPO_PUBLIC_API_URL || 'https://gym.perritoemo.online';
