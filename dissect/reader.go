package dissect

import (
	"bufio"
	"bytes"
	"cmp"
	"encoding/binary"
	"errors"
	"io"
	"runtime"
	"slices"
	"sync"

	"github.com/klauspost/compress/zstd"
	"github.com/rs/zerolog/log"
)

var playerIndicator = []byte{0x22, 0x07, 0x94, 0x9B, 0xDC}

var strSep = []byte{0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}

type Reader struct {
	b                      []byte
	offset                 int
	queries                [][]byte
	listeners              [][]func(r *Reader) error
	time                   float64 // in seconds
	timeRaw                string  // raw dissect format
	lastDefuserPlayerIndex int
	planted                bool
	defuserCountdownStart  int     // offset of the current plant/disable countdown's first packet, -1 if none
	defuserCountdownLast   float64 // last countdown value, to spot a restarted countdown
	readyStates            []readyState
	readPartial            bool // reads up to the player info packets
	playersRead            int
	scoreboardEntities     map[string]*scoreboardEntity
	scoreboardKills        []string      // killer usernames, one per scoreboard kill increment
	Header                 Header        `json:"header"`
	MatchFeedback          []MatchUpdate `json:"matchFeedback"`
	Scoreboard             Scoreboard
}

// NewReader decompresses in using zstd and
// validates the dissect header.
func NewReader(in io.Reader) (r *Reader, err error) {
	br := bufio.NewReader(in)
	chunkedCompression, err := testFileCompression(br)
	if err != nil {
		return r, err
	}
	log.Debug().Bool("chunkedCompression (>=Y8S4)", chunkedCompression).Send()
	r = &Reader{
		readPartial:            false,
		lastDefuserPlayerIndex: -1,
		defuserCountdownStart:  -1,
	}
	if chunkedCompression {
		if err = r.readChunkedData(br); err != nil {
			return r, err
		}
	} else {
		if err = r.readNonChunkedData(br); err != nil {
			return r, err
		}
	}
	log.Debug().Int("size", len(r.b)).Send()
	log.Debug().Str("season", r.Header.GameVersion).Int("code", r.Header.CodeVersion).Send()
	r.Listen(playerIndicator, readPlayer)
	r.Listen(scoreboardEntityIndicator, readScoreboardEntity)
	r.Listen([]byte{0x22, 0xA9, 0x26, 0x0B, 0xE4}, readAtkOpSwap)
	r.Listen([]byte{0xAF, 0x98, 0x99, 0xCA}, readSpawn)
	if r.Header.CodeVersion >= Y8S1 {
		r.Listen([]byte{0x1F, 0x07, 0xEF, 0xC9}, readTime)
	} else {
		r.Listen([]byte{0x1E, 0xF1, 0x11, 0xAB}, readY7Time)
	}
	r.Listen([]byte{0x59, 0x34, 0xE5, 0x8B, 0x04}, readMatchFeedback)
	r.Listen([]byte{0x22, 0xA9, 0xC8, 0x58, 0xD9}, readDefuserTimer)
	r.Listen(readyStateIndicator, readReadyState)
	r.Listen([]byte{0xEC, 0xDA, 0x4F, 0x80}, readScoreboardScore)
	r.Listen([]byte{0x4D, 0x73, 0x7F, 0x9E}, readScoreboardAssists)
	r.Listen([]byte{0x1C, 0xD2, 0xB1, 0x9D}, readScoreboardKills)
	return r, err
}

func (r *Reader) readChunkedData(genericReader io.Reader) error {
	log.Debug().Msg("reading data")
	temp, err := io.ReadAll(genericReader)
	if err != nil {
		return err
	}
	r.b = temp
	log.Debug().Msg("reading header magic")
	if err := r.readHeaderMagic(); err != nil {
		return err
	}
	log.Debug().Msg("reading header")
	h, err := r.readHeader()
	r.Header = h
	if err != nil {
		return err
	}
	log.Debug().Msg("decompressing data")
	zstdMagic := []byte{0x28, 0xB5, 0x2F, 0xFD}
	zstdReader, _ := zstd.NewReader(nil, zstd.WithDecoderConcurrency(1))
	defer zstdReader.Close()
	memoryReader := bytes.NewReader(nil)
	patternIndex := 0
	sections := 0
	var data bytes.Buffer
	for !errors.Is(err, io.EOF) {
		for patternIndex != 4 {
			b, scanErr := r.Bytes(1)
			if errors.Is(scanErr, io.EOF) {
				err = scanErr
				break
			}
			if scanErr != nil {
				return scanErr
			}
			if b[0] == zstdMagic[patternIndex] {
				patternIndex++
			} else {
				patternIndex = 0
			}
		}
		if errors.Is(err, io.EOF) {
			break
		}
		sections++
		patternIndex = 0
		memoryReader.Reset(r.b[r.offset-4:])
		tempReader := countedReader{memoryReader, 0}
		if err = zstdReader.Reset(&tempReader); err != nil {
			return err
		}
		// decode straight onto the end of data, rather than into a new buffer per section
		n, err := zstdReader.WriteTo(&data)
		if err != nil && !(n > 0 && errors.Is(err, zstd.ErrMagicMismatch)) {
			return err
		}
		r.offset += tempReader.n
	}
	r.b = data.Bytes()
	r.offset = 0
	log.Debug().Int("zstd_sections", sections).Send()
	return nil
}

func (r *Reader) readNonChunkedData(genericReader io.Reader) error {
	zstdReader, err := zstd.NewReader(genericReader)
	if err != nil {
		return err
	}
	decompressed, err := io.ReadAll(zstdReader)
	if err != nil && !(len(decompressed) > 0 && errors.Is(err, zstd.ErrMagicMismatch)) {
		return err
	}
	r.b = decompressed
	if err = r.readHeaderMagic(); err != nil {
		return err
	}
	h, err := r.readHeader()
	r.Header = h
	return err
}

type match struct {
	offset        int // index of the pattern's last byte
	listenerIndex int
}

// findQueries returns every occurrence of every query in r.b[start:end], in replay order.
// Each query is searched for on its own goroutine with bytes.Index, which is many times
// faster than comparing every byte against every query.
func (r *Reader) findQueries(start, end int) []match {
	if start < 0 || start >= end {
		return nil
	}
	b := r.b[start:end]
	found := make([][]match, len(r.queries))
	var wg sync.WaitGroup
	for j, query := range r.queries {
		if len(query) == 0 {
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; ; {
				k := bytes.Index(b[i:], query)
				if k < 0 {
					return
				}
				i += k + len(query)
				found[j] = append(found[j], match{start + i - 1, j})
			}
		}()
	}
	wg.Wait()
	matches := slices.Concat(found...)
	slices.SortFunc(matches, func(a, b match) int {
		return cmp.Or(cmp.Compare(a.offset, b.offset), cmp.Compare(a.listenerIndex, b.listenerIndex))
	})
	return matches
}

// Read continues reading the replay past the header until the EOF.
func (r *Reader) Read() (err error) {
	end := len(r.b)
	if r.readPartial {
		end /= 3
	}
	matches := r.findQueries(r.offset, end)
	log.Debug().Int("matches", len(matches)).Msg("calling listeners")
	for _, entry := range matches {
		for _, listener := range r.listeners[entry.listenerIndex] {
			r.offset = entry.offset + 1
			if err = listener(r); err != nil {
				return
			}
		}
	}
	if !r.readPartial {
		r.roundEnd()
	}
	r.b = nil
	return err
}

// ReadPartial continues reading the replay past the header until the full player list is read.
// This information does not include dynamic data, such as attack operator swaps.
// Use ReadPartial for faster, minimal reads.
func (r *Reader) ReadPartial() error {
	r.readPartial = true
	log.Debug().Msg("using partial read")
	err := r.Read()
	r.readPartial = false
	return err
}

// Listen registers a callback to be run during Read whenever
// the pattern is found.
func (r *Reader) Listen(pattern []byte, callback func(r *Reader) error) {
	var i int
	for i = 0; i < len(r.queries); i++ {
		if bytes.Equal(r.queries[i], pattern) {
			r.listeners[i] = append(r.listeners[i], callback)
			return
		}
	}
	r.queries = append(r.queries, pattern)
	r.listeners = append(r.listeners, []func(reader *Reader) error{callback})
}

// Seek skips through the replay until the pattern is found.
func (r *Reader) Seek(pattern []byte) error {
	start := r.offset
	i := 0
	for {
		b, err := r.Bytes(1)
		if err != nil {
			if Ok(err) {
				pc, _, _, ok := runtime.Caller(1)
				details := runtime.FuncForPC(pc)
				if ok && details != nil {
					log.Warn().Int("bytes", r.offset-start).Interface("func", details.Name()).Msg("large seek")
				} else {
					log.Warn().Int("bytes", r.offset-start).Msg("large seek")
				}
			}
			return err
		}
		if b[0] != pattern[i] {
			i = 0
			continue
		}
		i++
		if i == len(pattern) {
			return nil
		}
	}
}

// Skip increases the replay offset by n bytes.
func (r *Reader) Skip(n int) error {
	r.offset += n
	if r.offset >= len(r.b) {
		return io.EOF
	}
	return nil
}

func (r *Reader) Bytes(n int) ([]byte, error) {
	if err := r.Skip(n); err != nil {
		return []byte{}, err
	}
	return r.b[r.offset-n : r.offset], nil
}

func (r *Reader) Int() (int, error) {
	b, err := r.Bytes(1)
	if err != nil {
		return -1, err
	}
	return int(b[0]), nil
}

func (r *Reader) String() (string, error) {
	size, err := r.Int()
	if err != nil {
		return "", err
	}
	b, err := r.Bytes(size)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

func (r *Reader) Uint32() (uint32, error) {
	if err := r.Skip(1); err != nil { // size- unnecessary since we already know the length
		return 0, err
	}
	b, err := r.Bytes(4)
	if err != nil {
		return 0, err
	}
	return binary.LittleEndian.Uint32(b), nil
}

func (r *Reader) Uint64() (uint64, error) {
	if err := r.Skip(1); err != nil { // size- unnecessary since we already know the length
		return 0, err
	}
	b, err := r.Bytes(8)
	if err != nil {
		return 0, err
	}
	return binary.LittleEndian.Uint64(b), nil
}

func (r *Reader) Write(w io.Writer) (n int, err error) {
	return w.Write(r.b)
}
