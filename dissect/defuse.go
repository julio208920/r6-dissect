package dissect

import (
	"bytes"
	"strconv"
	"strings"

	"github.com/rs/zerolog/log"
)

// Newer replays (seen on Y11S3) no longer put the player ID in the defuser packet. The player who
// plants or disables the defuser is found through their controller's "weapon ready" field instead,
// which turns false as they start the interaction and stays false until it completes:
//
//	<controller id> 00000000 a4dc8dd4 01 <ready>
var readyStateIndicator = []byte{0xA4, 0xDC, 0x8D, 0xD4, 0x01}

// interactionSlack is how far (in bytes) past the countdown's first packet the interacting
// player's ready field may still turn false. It is usually written in the same packet.
const interactionSlack = 2048

type readyState struct {
	offset int
	player int
	ready  bool
}

func readDefuserTimer(r *Reader) error {
	packet := r.offset
	timer, err := r.String()
	if err != nil {
		return err
	}
	if err = r.Skip(34); err != nil {
		return err
	}
	id, err := r.Bytes(4)
	if err != nil {
		return err
	}
	i := r.PlayerIndexByID(id)
	a := DefuserPlantStart
	if r.planted {
		a = DefuserDisableStart
	}
	if i > -1 {
		u := MatchUpdate{
			Type:          a,
			Username:      r.Header.Players[i].Username,
			Time:          r.timeRaw,
			TimeInSeconds: r.time,
		}
		r.MatchFeedback = append(r.MatchFeedback, u)
		log.Debug().Interface("match_update", u).Send()
		r.lastDefuserPlayerIndex = i
	}
	if !strings.HasPrefix(timer, "0.00") {
		r.trackDefuserCountdown(packet, timer)
		return nil
	}
	// A lone "0.00" without a countdown before it is not a plant or disable;
	// one also shows up right after a plant completes.
	start := r.defuserCountdownStart
	r.defuserCountdownStart = -1
	if start < 0 {
		log.Debug().Str("timer", timer).Msg("ignoring defuser timer without a countdown")
		return nil
	}
	a = DefuserDisableComplete
	role := Defense
	if !r.planted {
		a = DefuserPlantComplete
		role = Attack
		r.planted = true
	}
	if i = r.lastDefuserPlayerIndex; i < 0 {
		i = r.interactingPlayer(start, role)
	}
	username := ""
	if i > -1 {
		username = r.Header.Players[i].Username
	}
	u := MatchUpdate{
		Type:          a,
		Username:      username,
		Time:          r.timeRaw,
		TimeInSeconds: r.time,
	}
	r.MatchFeedback = append(r.MatchFeedback, u)
	log.Debug().Interface("match_update", u).Send()
	return nil
}

// trackDefuserCountdown remembers where the current plant/disable countdown started.
// The value jumping back up means a new countdown (an earlier attempt was cancelled).
func (r *Reader) trackDefuserCountdown(offset int, timer string) {
	if timer == "" {
		return
	}
	v, err := strconv.ParseFloat(timer, 64)
	if r.defuserCountdownStart < 0 || (err == nil && v > r.defuserCountdownLast+0.5) {
		r.defuserCountdownStart = offset
	}
	if err == nil {
		r.defuserCountdownLast = v
	}
}

// readReadyState records a player's weapon-ready field (see readyStateIndicator).
func readReadyState(r *Reader) error {
	start := r.offset - len(readyStateIndicator) - 8 // controller id, then 4 zero bytes
	if start < 1 || r.offset >= len(r.b) || r.b[start-1] != 0x23 ||
		!bytes.Equal(r.b[start+4:start+8], []byte{0x00, 0x00, 0x00, 0x00}) {
		return nil
	}
	id := r.b[start : start+4]
	for i, p := range r.Header.Players {
		if p.controllerID != nil && bytes.Equal(p.controllerID, id) {
			r.readyStates = append(r.readyStates, readyState{offset: r.offset, player: i, ready: r.b[r.offset] != 0})
			break
		}
	}
	return nil
}

// interactingPlayer returns the index of the living player on the given side who is planting or
// disabling the defuser in the countdown that started at start, or -1 if nobody fits: their ready
// field must be false at that point. A player whose field then stayed false until now is preferred,
// and among those, whoever's turned false last.
func (r *Reader) interactingPlayer(start int, role TeamRole) int {
	dead := make(map[string]bool)
	for _, u := range r.MatchFeedback {
		switch u.Type {
		case Kill:
			dead[u.Target] = true
		case Death:
			dead[u.Username] = true
		}
	}
	best, bestSince, bestStable := -1, 0, false
	for i, p := range r.Header.Players {
		if p.TeamIndex < 0 || p.TeamIndex >= len(r.Header.Teams) || r.Header.Teams[p.TeamIndex].Role != role || dead[p.Username] {
			continue
		}
		since, ready, stable := -1, true, true
		for _, s := range r.readyStates {
			if s.player != i {
				continue
			}
			if s.offset <= start+interactionSlack {
				since, ready = s.offset, s.ready
			} else if s.ready {
				stable = false
			}
		}
		if since < 0 || ready {
			continue
		}
		if best < 0 || (stable && !bestStable) || (stable == bestStable && since > bestSince) {
			best, bestSince, bestStable = i, since, stable
		}
	}
	return best
}
