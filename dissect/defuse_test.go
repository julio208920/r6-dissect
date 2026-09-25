package dissect

import "testing"

// planterTestReader has attackers a0-a3 (team 0) and defender d0 (team 1).
func planterTestReader(states ...readyState) *Reader {
	r := &Reader{defuserCountdownStart: -1, readyStates: states}
	r.Header.Teams[0].Role = Attack
	r.Header.Teams[1].Role = Defense
	for _, name := range []string{"a0", "a1", "a2", "a3"} {
		r.Header.Players = append(r.Header.Players, Player{Username: name, TeamIndex: 0})
	}
	r.Header.Players = append(r.Header.Players, Player{Username: "d0", TeamIndex: 1})
	return r
}

func TestInteractingPlayer(t *testing.T) {
	const start = 10000
	tests := []struct {
		name   string
		states []readyState
		dead   string
		want   int
	}{
		{
			name: "stays not-ready for the whole countdown",
			states: []readyState{
				{9000, 0, false},                   // a0: weapon away since before the countdown, never back
				{9500, 1, false}, {20000, 1, true}, // a1: weapon back out mid-countdown
				{10030, 4, false}, // d0: wrong side
			},
			want: 0,
		},
		{
			name: "latest to put their weapon away wins among steady players",
			states: []readyState{
				{9000, 0, false},
				{start + 30, 3, false},
			},
			want: 3,
		},
		{
			name: "falls back to someone whose weapon came back out",
			states: []readyState{
				{9000, 0, false}, {9800, 0, true}, // a0: ready when the countdown starts
				{start + 30, 1, false}, {start + 4000, 1, true},
			},
			want: 1,
		},
		{
			name:   "dead players are skipped",
			states: []readyState{{start + 30, 2, false}, {9000, 0, false}},
			dead:   "a2",
			want:   0,
		},
		{
			name:   "nobody fits",
			states: []readyState{{9000, 0, true}},
			want:   -1,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := planterTestReader(tt.states...)
			if tt.dead != "" {
				r.MatchFeedback = append(r.MatchFeedback, MatchUpdate{Type: Kill, Username: "d0", Target: tt.dead})
			}
			if got := r.interactingPlayer(start, Attack); got != tt.want {
				t.Errorf("interactingPlayer() = %d, want %d", got, tt.want)
			}
		})
	}
}

func TestTrackDefuserCountdown(t *testing.T) {
	r := planterTestReader()
	r.trackDefuserCountdown(100, "")
	if r.defuserCountdownStart != -1 {
		t.Fatalf("empty timer started a countdown at %d", r.defuserCountdownStart)
	}
	r.trackDefuserCountdown(200, "6.98")
	r.trackDefuserCountdown(300, "4.10")
	if r.defuserCountdownStart != 200 {
		t.Fatalf("countdown start = %d, want 200", r.defuserCountdownStart)
	}
	r.trackDefuserCountdown(400, "6.99") // cancelled attempt, new countdown
	if r.defuserCountdownStart != 400 {
		t.Fatalf("restarted countdown start = %d, want 400", r.defuserCountdownStart)
	}
}
