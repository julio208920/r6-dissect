"""
metrics_engine.py
==================
Computes R6 Pro League-style player stats from a normalized MatchData dict
(see parser.py). The per-player scoreboard mirrors the official R6 Esports
match page, one row per player:

    EPS | KD (+/-) | Entry | KOST | KPR | HS | SRV | Clutches | Multikills |
    Objectives | Dead for trade kill | Trade kills

Definitions (public conventions used by Pro League / SiegeGG / stats.cc):

- KD (+/-): kills-deaths and the difference, e.g. "12-8 (+4)".
- Entry: opening kills-opening deaths. The opening duel is the round's
  first death; its killer gets the entry kill, the victim the entry death.
- KOST: % of rounds with a Kill, Objective (plant/defuse), Survival, or
  where the player's death was Traded.
- KPR: kills per round.
- HS: headshot kills / kills.
- SRV: % of rounds survived.
- Clutches: rounds won as the last player alive on the team vs 1+ enemies.
- Multikills: rounds with 2+ kills.
- Objectives: defuser plants + defuser disables.
- Dead for trade kill: deaths that a teammate avenged by killing the
  killer within TRADE_WINDOW_SECONDS.
- Trade kills: kills of an enemy who had just killed a teammate, within
  TRADE_WINDOW_SECONDS of that teammate's death.
- EPS: a performance score centered on 100 for an average player in the
  match. Ubisoft hasn't published its EPS formula, so this one is built
  from the same ingredients (KPR, survival, KOST, entry differential,
  multikills, clutches, objectives, trades), z-scored across the match.

Team kills never count as kills (the victim still gets a death).

Event time: parser.py gives every event an "elapsed" value (seconds since
the round's first event, monotonic), since the in-game clock counts down
and resets when the defuser is planted. The demo match only has "time",
which already counts up.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

TRADE_WINDOW_SECONDS = 10.0

# pro_league_rows() column order, as shown on the R6 Esports match page
PRO_LEAGUE_COLUMNS = (
    "EPS", "KD (+/-)", "Entry", "KOST", "KPR", "HS", "SRV",
    "Clutches", "Multikills", "Objectives", "Dead for trade kill", "Trade kills",
)


@dataclass
class RoundBreakdown:
    round_num: int
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    survived: bool = True
    entry_kill: bool = False
    entry_death: bool = False
    traded: bool = False  # this player's death was traded ("dead for trade kill")
    trade_kills: int = 0  # kills that traded a teammate's death
    planted: bool = False
    defused: bool = False
    clutch: str | None = None  # e.g. "1v2" -- clutch WON
    clutch_attempt: str | None = None  # e.g. "1v3" -- left alone vs 1+ enemies, won or not
    headshots: int = 0
    kost: bool = False

    def summary(self) -> str:
        bits = [f"{self.kills}K"] if self.kills else []
        if self.assists:
            bits.append(f"{self.assists}A")
        bits.append("died" if self.deaths else "survived")
        for flag, label in (
            (self.entry_kill, "entry kill"), (self.entry_death, "entry death"),
            (self.traded, "traded"), (self.planted, "planted"), (self.defused, "defused"),
        ):
            if flag:
                bits.append(label)
        if self.trade_kills:
            bits.append(f"{self.trade_kills} trade kill{'s' if self.trade_kills > 1 else ''}")
        if self.clutch:
            bits.append(f"clutched {self.clutch}")
        return ", ".join(bits)


@dataclass
class PlayerStats:
    name: str
    team: int
    rounds_played: int = 0
    rounds_survived: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    headshots: int = 0
    entry_kills: int = 0
    entry_deaths: int = 0
    trades: int = 0  # deaths traded ("dead for trade kill")
    trade_kills: int = 0
    plants: int = 0
    defuses: int = 0
    kost_rounds: int = 0
    clutches: dict = field(default_factory=lambda: {i: 0 for i in range(1, 6)})
    multikill_rounds: int = 0
    round_breakdown: list = field(default_factory=list)
    rating: float = 1.0

    def _per_round(self, n: int) -> float:
        return n / self.rounds_played if self.rounds_played else 0.0

    @property
    def kd(self) -> float:
        return self.kills / self.deaths if self.deaths else float(self.kills)

    @property
    def kost_pct(self) -> float:
        return 100.0 * self._per_round(self.kost_rounds)

    @property
    def srv_pct(self) -> float:
        return 100.0 * self._per_round(self.rounds_survived)

    @property
    def hs_pct(self) -> float:
        return 100.0 * self.headshots / self.kills if self.kills else 0.0

    @property
    def kpr(self) -> float:
        return self._per_round(self.kills)

    @property
    def dpr(self) -> float:
        return self._per_round(self.deaths)

    @property
    def objectives(self) -> int:
        return self.plants + self.defuses

    @property
    def total_clutches(self) -> int:
        return sum(self.clutches.values())

    @property
    def eps(self) -> int:
        return round(100 * self.rating)


def _team_of(players: list[dict]) -> dict[str, int]:
    return {p["name"]: p["team"] for p in players}


def _clutch_label(size: int) -> str:
    return f"1v{min(max(size, 1), 5)}"


def _process_round(rnd: dict, team_of: dict[str, int], stats: dict[str, PlayerStats]) -> None:
    # Events are consumed in feed order, which is chronological (see parser.py).
    round_num = rnd["round_num"]
    winner_team = rnd.get("winner_team")

    # only players present this round (leavers / late joiners in long matches);
    # the demo data has no per-round roster, so it falls back to everyone.
    present = [n for n in (rnd.get("players") or team_of) if n in team_of]
    rb = {name: RoundBreakdown(round_num=round_num) for name in present}
    alive = {0: set(), 1: set()}
    for name in present:
        alive[team_of[name]].add(name)

    attackers = rnd.get("attack_team")
    first_death_seen = False
    deaths = []  # (time, victim, killer) in feed order, for trade detection
    kills = []   # (time, killer, victim)
    alone = {}   # side -> (last player alive, enemies alive at that moment)

    for e in rnd["events"]:
        etype, actor = e["type"], e.get("actor")
        t = e.get("elapsed", e.get("time", 0.0))

        if etype == "kill":
            victim = e.get("target")
            if actor not in rb or victim not in rb:
                continue
            if team_of[actor] == team_of[victim]:
                continue  # team kill: no kill credit; the victim's death is its own event
            rb[actor].kills += 1
            rb[actor].headshots += bool(e.get("headshot"))
            kills.append((t, actor, victim))

        elif etype == "death":
            if actor not in rb or rb[actor].deaths:
                continue
            killer = e.get("killed_by")
            rb[actor].deaths = 1
            rb[actor].survived = False
            if not first_death_seen:
                first_death_seen = True
                rb[actor].entry_death = True
                if killer in rb and team_of[killer] != team_of[actor]:
                    rb[killer].entry_kill = True
            deaths.append((t, actor, killer))
            alive[team_of[actor]].discard(actor)
            for side in (0, 1):
                if side not in alone and len(alive[side]) == 1 and alive[1 - side]:
                    alone[side] = (next(iter(alive[side])), len(alive[1 - side]))

        elif etype in ("plant", "defuse"):
            # r6-dissect names the player; if it couldn't, credit the plant/defuse
            # only when exactly one player on the acting side was still alive
            if actor is None and attackers in (0, 1):
                side = attackers if etype == "plant" else 1 - attackers
                if len(alive[side]) == 1:
                    actor = next(iter(alive[side]))
            if actor in rb:
                if etype == "plant":
                    rb[actor].planted = True
                else:
                    rb[actor].defused = True

    # Trades: victim V killed by K; a teammate of V kills K within the window.
    used_kills = set()
    for dt, victim, killer in deaths:
        if killer not in rb or team_of[killer] == team_of[victim]:
            continue
        for i, (kt, avenger, target) in enumerate(kills):
            if target != killer or kt < dt or kt - dt > TRADE_WINDOW_SECONDS:
                continue
            if team_of[avenger] != team_of[victim] or avenger == victim:
                continue
            rb[victim].traded = True
            if i not in used_kills:
                used_kills.add(i)
                rb[avenger].trade_kills += 1
            break

    # Clutch: a side's last player alive vs 1+ enemies; won if that side won the round.
    for side, (name, enemies) in alone.items():
        rb[name].clutch_attempt = _clutch_label(enemies)
        if side == winner_team:
            rb[name].clutch = rb[name].clutch_attempt

    # assists come from r6-dissect's scoreboard read; the kill feed can't give them
    for name, auth in (rnd.get("round_stats") or {}).items():
        if name in rb:
            rb[name].assists = auth["assists"]

    for name, r in rb.items():
        r.kost = bool(r.kills or r.planted or r.defused or r.survived or r.traded)
        s = stats[name]
        s.rounds_played += 1
        s.rounds_survived += r.survived
        s.kills += r.kills
        s.deaths += r.deaths
        s.assists += r.assists
        s.headshots += r.headshots
        s.plants += r.planted
        s.defuses += r.defused
        s.entry_kills += r.entry_kill
        s.entry_deaths += r.entry_death
        s.trades += r.traded
        s.trade_kills += r.trade_kills
        s.kost_rounds += r.kost
        s.multikill_rounds += r.kills >= 2
        if r.clutch:
            s.clutches[int(r.clutch[-1])] += 1
        s.round_breakdown.append(r)


def _compute_ratings(stats: dict[str, PlayerStats]) -> None:
    """z-score each ingredient across the players in this match and
    recenter at 1.00 (EPS = 100 * rating)."""
    players = [p for p in stats.values() if p.rounds_played]
    if not players:
        return

    # (weight, per-player value); a negative weight penalizes
    ingredients = [
        (0.30, lambda p: p.kpr),
        (-0.20, lambda p: p.dpr),
        (0.18, lambda p: p.kost_pct),
        (0.14, lambda p: p._per_round(p.entry_kills - p.entry_deaths)),
        (0.06, lambda p: p._per_round(p.multikill_rounds)),
        (0.05, lambda p: p._per_round(p.total_clutches)),
        (0.04, lambda p: p._per_round(p.objectives)),
        (0.03, lambda p: p._per_round(p.trade_kills)),
    ]
    composite = {p.name: 0.0 for p in players}
    for weight, value in ingredients:
        vals = [value(p) for p in players]
        mean = sum(vals) / len(vals)
        sd = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        for p, v in zip(players, vals):
            composite[p.name] += weight * (v - mean) / sd
    for p in players:
        # ~0.15 rating points per composite std-dev unit
        p.rating = round(1.00 + 0.15 * composite[p.name], 3)


def compute_match_metrics(match: dict) -> dict[str, PlayerStats]:
    """Main entry point. Returns {player_name: PlayerStats}."""
    team_of = _team_of(match["players"])
    stats = {name: PlayerStats(name=name, team=t) for name, t in team_of.items()}
    for rnd in match["rounds"]:
        _process_round(rnd, team_of, stats)
    _compute_ratings(stats)
    return stats


def _diff(a: int, b: int) -> str:
    d = a - b
    return f"{a}-{b} ({'+' if d > 0 else ''}{d})"


def _num(x: float) -> str:
    """0.92 -> "0.92", 1.0 -> "1", 0.5 -> "0.5" (how the Pro League page prints KPR)."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


def pro_league_rows(stats: dict[str, PlayerStats]) -> list[dict]:
    """One display row per player, in the R6 Esports match-page layout,
    sorted by team then EPS (desc)."""
    rows = []
    for s in sorted(stats.values(), key=lambda s: (s.team, -s.rating, s.name.lower())):
        rows.append({
            "Team": s.team,
            "Player": s.name,
            "EPS": s.eps,
            "KD (+/-)": _diff(s.kills, s.deaths),
            "Entry": _diff(s.entry_kills, s.entry_deaths),
            "KOST": f"{s.kost_pct:.0f}%",
            "KPR": _num(s.kpr),
            "HS": f"{s.hs_pct:.0f}%",
            "SRV": f"{s.srv_pct:.0f}%",
            "Clutches": s.total_clutches,
            "Multikills": s.multikill_rounds,
            "Objectives": s.objectives,
            "Dead for trade kill": s.trades,
            "Trade kills": s.trade_kills,
        })
    return rows


def scoreboard_text(match: dict, rows: list[dict]) -> str:
    """Plain-text scoreboard (pro_league_rows), one table per team, like the R6 Esports match page."""
    cols = ("Player",) + PRO_LEAGUE_COLUMNS
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols} if rows else {c: len(c) for c in cols}
    names, score = match["team_names"], match["final_score"]
    out = [f"{match['map']}  |  {names[0]} {score[0]} - {score[1]} {names[1]}  |  {len(match['rounds'])} round(s)"]
    for team in (0, 1):
        out += ["", names[team], "  ".join(c.ljust(widths[c]) for c in cols)]
        out += ["  ".join(str(r[c]).ljust(widths[c]) for c in cols) for r in rows if r["Team"] == team]
    return "\n".join(out)


def leaderboard_rows(stats: dict[str, PlayerStats]) -> list[dict]:
    """Numeric rows (sortable, CSV-friendly), sorted by EPS desc."""
    rows = [{
        "Player": s.name,
        "Team": s.team,
        "EPS": s.eps,
        "Rounds": s.rounds_played,
        "K": s.kills,
        "D": s.deaths,
        "A": s.assists,
        "+/-": s.kills - s.deaths,
        "Entry K": s.entry_kills,
        "Entry D": s.entry_deaths,
        "KOST%": round(s.kost_pct, 1),
        "KPR": round(s.kpr, 2),
        "HS%": round(s.hs_pct, 1),
        "SRV%": round(s.srv_pct, 1),
        "Clutches": s.total_clutches,
        "Multikills": s.multikill_rounds,
        "Plants": s.plants,
        "Defuses": s.defuses,
        "Objectives": s.objectives,
        "Dead for trade kill": s.trades,
        "Trade kills": s.trade_kills,
    } for s in stats.values()]
    rows.sort(key=lambda r: r["EPS"], reverse=True)
    return rows


def rows_csv(rows: list[dict]) -> str:
    """Rows that share their keys (e.g. leaderboard_rows) as CSV text, columns in key order."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else [])
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()
