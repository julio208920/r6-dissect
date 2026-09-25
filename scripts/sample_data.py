"""
sample_data.py
===============
A deterministic, hand-tuned synthetic match in the internal MatchData
schema (see parser.py docstring). Used for the app's "Demo Mode" so the
UI, metrics engine, and rating formula can be exercised and verified
without needing r6-dissect installed or a real .rec file on hand.

9 rounds on Bank, Team Liquid (team 0) vs Spacestation (team 1),
final score 5-4 to Liquid. Includes at least one clutch (1v2), several
entry kills/deaths, a trade, and a multi-kill round, so every metric in
metrics_engine.py has at least one non-zero example to validate against.
"""

TEAM0 = ["Fabian", "Kanto", "Sens", "Sacri", "BC"]
TEAM1 = ["Bosco", "HotShot", "Otter", "Solotov", "Nyx"]

PLAYERS = (
    [{"name": n, "team": 0, "operator_history": ["Ash"]} for n in TEAM0]
    + [{"name": n, "team": 1, "operator_history": ["Jager"]} for n in TEAM1]
)


def _round(round_num, winner_team, win_condition, site, events, dead_by_end):
    """dead_by_end: list of player names eliminated at some point this round
    (used only for readability here; the engine derives state from events)."""
    return {
        "round_num": round_num,
        "winner_team": winner_team,
        "win_condition": win_condition,
        "site": site,
        "events": events,
        "alive_start": {"team0": TEAM0, "team1": TEAM1},
    }


def K(t, actor, target, headshot=False, weapon="R4-C"):
    return {"type": "kill", "time": t, "actor": actor, "target": target,
            "headshot": headshot, "weapon": weapon}


def D(t, actor, killed_by):
    return {"type": "death", "time": t, "actor": actor, "killed_by": killed_by}


def P(t, actor):
    return {"type": "plant", "time": t, "actor": actor}


def DF(t, actor):
    return {"type": "defuse", "time": t, "actor": actor}


def kd(t, killer, victim, headshot=False, weapon="R4-C"):
    return [K(t, killer, victim, headshot, weapon), D(t, victim, killer)]


ROUNDS = []

# Round 1: Liquid attacks, entry kill by Fabian, plant, Liquid wins on kills
ev = []
ev += kd(8.0, "Fabian", "Bosco", headshot=True)          # entry kill/death
ev += kd(22.0, "Kanto", "HotShot")
ev += kd(35.0, "Otter", "Sens")
ev += kd(40.0, "Solotov", "BC")
ev.append(P(55.0, "Kanto"))
ev += kd(70.0, "Sacri", "Otter")
ev += kd(72.0, "Nyx", "Sacri")                            # trade window test
ev += kd(90.0, "Fabian", "Solotov")
ev += kd(95.0, "Fabian", "Nyx")                            # 3k round for Fabian
ROUNDS.append(_round(1, 0, "kills", "Kids/Rooms", ev, []))

# Round 2: Spacestation attacks, entry by HotShot, defuses fail, kills win
ev = []
ev += kd(10.0, "HotShot", "Sens", headshot=True)
ev += kd(28.0, "Fabian", "Otter")
ev += kd(44.0, "Nyx", "Kanto")
ev += kd(60.0, "Bosco", "Sacri")
ev += kd(65.0, "BC", "Bosco")                              # trade
ev += kd(80.0, "Solotov", "BC")
ROUNDS.append(_round(2, 1, "kills", "CCTV/Archives", ev, []))

# Round 3: Liquid attacks, plant + defuse fails, Liquid wins on plant
ev = []
ev += kd(12.0, "Sacri", "Nyx")
ev += kd(30.0, "Otter", "Kanto")
ev.append(P(48.0, "Sens"))
ev += kd(60.0, "Fabian", "Solotov")
ev += kd(75.0, "Sens", "Otter")
ev += kd(85.0, "HotShot", "Sens")
ev += kd(95.0, "Sacri", "HotShot")
ev += kd(96.0, "BC", "Bosco")
ROUNDS.append(_round(3, 0, "bomb_detonated", "Kids/Rooms", ev, []))

# Round 4: Spacestation defends and wins on time (no full wipe), Fabian entry death
ev = []
ev += kd(6.0, "Otter", "Fabian", headshot=True)            # entry death for Fabian
ev += kd(20.0, "Kanto", "Nyx")
ev += kd(50.0, "Bosco", "Kanto")
ev += kd(70.0, "Sens", "HotShot")
ev += kd(88.0, "Solotov", "Sens")
ev += kd(89.0, "Sacri", "Solotov")
ev += kd(100.0, "Bosco", "Sacri")
ev += kd(101.0, "BC", "Bosco")
# BC is now the lone survivor for team0 vs Otter -> BC clutches a 1v1
ev += kd(115.0, "BC", "Otter")
ROUNDS.append(_round(4, 0, "kills", "CCTV/Archives", ev, []))

# Round 5: Spacestation attacks, wins on plant, Sacri multi-kill (2k)
ev = []
ev += kd(9.0, "Nyx", "Kanto", headshot=True)
ev += kd(25.0, "Sacri", "Otter")
ev += kd(26.0, "Sacri", "Solotov")
ev += kd(40.0, "HotShot", "Sacri")
ev += kd(58.0, "Bosco", "Fabian")
ev += kd(59.0, "BC", "Bosco")
ev.append(P(70.0, "Nyx"))
ev += kd(85.0, "Nyx", "BC")
ROUNDS.append(_round(5, 1, "bomb_detonated", "Kids/Rooms", ev, []))

# Round 6: Liquid attacks, Fabian clutches a 1v2
ev = []
ev += kd(11.0, "Fabian", "Bosco", headshot=True)
ev += kd(29.0, "Kanto", "HotShot")
ev += kd(41.0, "Otter", "Kanto")
ev += kd(52.0, "Solotov", "Sens")
ev += kd(60.0, "Nyx", "Sacri")
ev += kd(65.0, "Otter", "BC")
ev.append(P(75.0, "Fabian"))
# Fabian now alone vs Otter, Solotov, Nyx -> wins a 1v3 clutch
ev += kd(90.0, "Fabian", "Otter")
ev += kd(100.0, "Fabian", "Solotov")
ev += kd(108.0, "Fabian", "Nyx")
ROUNDS.append(_round(6, 0, "bomb_detonated", "CCTV/Archives", ev, []))

# Round 7: Spacestation defends, wins on time; BC entry death, no trade
ev = []
ev += kd(7.0, "Otter", "BC")
ev += kd(24.0, "HotShot", "Sens")
ev += kd(38.0, "Bosco", "Sacri")
ev += kd(52.0, "Nyx", "Fabian")
ev += kd(66.0, "Solotov", "Kanto")
ROUNDS.append(_round(7, 1, "time", "Kids/Rooms", ev, []))

# Round 8: Liquid attacks, wins on plant, Kanto entry kill
ev = []
ev += kd(9.0, "Kanto", "Solotov", headshot=True)
ev += kd(24.0, "Sens", "Nyx")
ev += kd(36.0, "Otter", "Sacri")
ev += kd(37.0, "Fabian", "Otter")
ev.append(P(50.0, "BC"))
ev += kd(66.0, "HotShot", "BC")
ev += kd(80.0, "Kanto", "HotShot")
ev += kd(90.0, "Kanto", "Bosco")
ROUNDS.append(_round(8, 0, "bomb_detonated", "CCTV/Archives", ev, []))

# Round 9: Spacestation attacks, Liquid wins on kills (match point, 5-4)
ev = []
ev += kd(10.0, "Sacri", "Bosco")
ev += kd(24.0, "Fabian", "HotShot", headshot=True)
ev += kd(36.0, "Kanto", "Otter")
ev += kd(48.0, "Nyx", "Sens")
ev += kd(60.0, "Solotov", "Kanto")
ev += kd(61.0, "Sacri", "Solotov")
ev += kd(70.0, "Sacri", "Nyx")
ROUNDS.append(_round(9, 0, "kills", "Kids/Rooms", ev, []))


SAMPLE_MATCH = {
    "map": "Bank",
    "match_id": "demo-match-0001",
    "team_names": ["Team Liquid", "Spacestation Gaming"],
    "final_score": [5, 4],
    "players": PLAYERS,
    "rounds": ROUNDS,
}
