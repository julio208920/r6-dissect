package dissect

import "testing"

func TestMatchReaderListenReusesPattern(t *testing.T) {
	m := &MatchReader{}
	pattern := []byte{0x01, 0x02}
	callback := func(*Reader) error { return nil }

	m.Listen(pattern, callback)
	m.Listen(pattern, callback)

	if len(m.queries) != 1 {
		t.Fatalf("registered %d queries, want 1", len(m.queries))
	}
	if got := len(m.listeners[0]); got != 2 {
		t.Fatalf("registered %d callbacks, want 2", got)
	}
}