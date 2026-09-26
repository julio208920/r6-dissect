const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");

export interface PlayerSeason {
  username: string;
  team?: string | null;
  totals: Record<string, number>;
  kd: number;
  kost_pct: number;
  entry_diff: number;
  hs_pct: number;
  clutches_won: number;
  eps?: number | null; // null for matches saved before EPS was recorded
}

export interface TeamSeason {
  team: string;
  players: string[];
  totals: Record<string, number>;
  kd: number;
  entry_diff: number;
  clutch_success_rate: number | null;
  kost_avg: number;
  eps?: number | null;
  member_stats: PlayerSeason[];
}

export interface SeasonSummary {
  season: string;
  rounds_logged: number;
  tracked_players: Record<string, string | null>;
  players: PlayerSeason[];
  teams: TeamSeason[];
}

export interface MatchHistoryItem {
  match_id: string;
  saved_at: string;
  rounds: number;
  players: number;
}

export interface SchoolTeam {
  name: string;
  game: string;
  roster: string[];
  standings?: unknown;
  matches?: unknown[];
}

export interface School {
  name: string;
  logo_url?: string;
  primary_color?: string;
  teams: SchoolTeam[];
}

export interface NormalizedMatch {
  map: string;
  match_id: string;
  team_names: string[];
  final_score: number[];
  players: { name: string; team: number; operator_history?: string[] }[];
  rounds: {
    round_num: number;
    winner_team: number | null;
    site: string;
    operators?: Record<string, string>;
    events: { type: string; actor?: string; target?: string }[];
  }[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json() as { detail?: string };
      detail = body.detail || detail;
    } catch {
      // Use the HTTP status when the API did not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  summary: (season: string) => request<SeasonSummary>(`/seasons/${encodeURIComponent(season)}/summary`),
  matches: (season: string) => request<{ matches: MatchHistoryItem[] }>(`/seasons/${encodeURIComponent(season)}/matches`),
  schools: () => request<{ schools: School[]; source: string }>("/schools"),
  importCatalog: async (file: File) => {
    const payload = JSON.parse(await file.text()) as unknown;
    return request<{ schools: School[]; source: string }>("/schools/catalog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  parseReplays: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<{ matches: { name: string; match: NormalizedMatch; warnings: string[] }[]; skipped: string | null }>(
      "/replays/parse", { method: "POST", body: form },
    );
  },
  parseReplayPath: (path: string) => request<{
    matches: { name: string; match: NormalizedMatch; warnings: string[] }[];
    skipped: string | null;
  }>("/replays/parse-path", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  }),
  logMatch: (season: string, match: NormalizedMatch, rosters: Record<string, string[]>) =>
    request<{ rounds_logged: number; rounds_skipped_duplicate: number; warnings: string[] }>(
      `/seasons/${encodeURIComponent(season)}/matches/log`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match, rosters }),
      },
    ),
  trackRoster: (season: string, team: string, players: string[]) =>
    request<{ tracked_players: Record<string, string | null> }>(`/seasons/${encodeURIComponent(season)}/rosters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ team, players }),
    }),
};