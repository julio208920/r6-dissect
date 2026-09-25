package dissect

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/rs/zerolog/log"
)

func readTime(r *Reader) error {
	time, err := r.Uint32()
	if err != nil {
		return err
	}
	r.time = float64(time)
	r.timeRaw = fmt.Sprintf("%d:%02d", time/60, time%60)
	return nil
}

func readY7Time(r *Reader) error {
	time, err := r.String()
	parts := strings.Split(time, ":")
	if len(parts) == 1 {
		seconds, err := strconv.ParseFloat(parts[0], 64)
		if err != nil {
			return err
		}
		r.time = seconds
		r.timeRaw = parts[0]
		return nil
	}
	minutes, err := strconv.Atoi(parts[0])
	if err != nil {
		return err
	}
	seconds, err := strconv.Atoi(parts[1])
	if err != nil {
		return err
	}
	r.time = float64((minutes * 60) + seconds)
	r.timeRaw = time
	return nil
}

func (r *Reader) roundEnd() {
	log.Debug().Msg("round_end")

	planted := false
	deaths := make(map[int]int)
	sizes := make(map[int]int)
	roles := make(map[int]TeamRole)

	for _, p := range r.Header.Players {
		sizes[p.TeamIndex] += 1
		roles[p.TeamIndex] = r.Header.Teams[p.TeamIndex].Role
	}
	teamOf := func(username string) int {
		if i := r.PlayerIndexByUsername(username); i > -1 {
			return r.Header.Players[i].TeamIndex
		}
		return -1
	}
	teamWithRole := func(role TeamRole) int {
		for i := range r.Header.Teams {
			if r.Header.Teams[i].Role == role {
				return i
			}
		}
		return -1
	}

	// Y9S4+ headers tell us who won via StartingScore, so the feed is only used for the win condition.
	// Neither score moving means the round was cut short (e.g. an abandoned match).
	headerWinner := -1
	if r.Header.CodeVersion >= Y9S4 {
		for i := range r.Header.Teams {
			if r.Header.Teams[i].StartingScore < r.Header.Teams[i].Score {
				headerWinner = i
			}
			r.Header.Teams[i].Won = false
		}
	}

	r.fixKillersFromScoreboard()

	defenders := teamWithRole(Defense)
	disabled := false
	feedback := r.MatchFeedback[:0]
	for _, u := range r.MatchFeedback {
		switch u.Type {
		case Kill:
			if i := teamOf(u.Target); i > -1 {
				deaths[i]++
			}
		case Death:
			if i := teamOf(u.Username); i > -1 {
				deaths[i]++
			}
		case DefuserPlantComplete:
			planted = true
		case DefuserDisableComplete:
			// the "0.00" timer that marks a disable can also appear when the bomb goes off,
			// so drop it when the header says the defenders did not win the round.
			if disabled || (headerWinner > -1 && headerWinner != defenders) {
				log.Debug().Interface("match_update", u).Msg("dropping defuser disable, defenders did not win")
				continue
			}
			disabled = true
		}
		feedback = append(feedback, u)
	}
	r.MatchFeedback = feedback

	if r.Header.CodeVersion >= Y9S4 && headerWinner < 0 {
		return
	}
	winner, condition := r.winCondition(headerWinner, planted, disabled, deaths, sizes, roles)
	if winner < 0 {
		return
	}
	r.Header.Teams[winner].Won = true
	r.Header.Teams[winner].WinCondition = condition
}

// winCondition returns the winning team index and how the round was won, or -1 if unknown.
func (r *Reader) winCondition(headerWinner int, planted, disabled bool, deaths, sizes map[int]int, roles map[int]TeamRole) (int, WinCondition) {
	attackers, defenders := 0, 1
	if roles[0] == Defense {
		attackers, defenders = 1, 0
	}
	// once planted, defenders can only win by disabling the defuser
	if disabled || (planted && headerWinner == defenders) {
		return defenders, DisabledDefuser
	}
	if headerWinner > -1 {
		loser := headerWinner ^ 1
		switch {
		case sizes[loser] > 0 && deaths[loser] >= sizes[loser]:
			return headerWinner, KilledOpponents
		case headerWinner == attackers && planted:
			return headerWinner, DefusedBomb
		case headerWinner == defenders:
			return headerWinner, Time
		}
		return headerWinner, ""
	}
	if planted {
		return attackers, DefusedBomb
	}
	if deaths[0] == sizes[0] {
		return 1, KilledOpponents
	}
	if deaths[1] == sizes[1] {
		return 0, KilledOpponents
	}
	return defenders, Time
}
