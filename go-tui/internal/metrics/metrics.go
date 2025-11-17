package metrics

import (
    "bufio"
    "encoding/json"
    "io"
    "os"
    "path/filepath"
    "sort"
    "time"
)

type Entry struct {
    TS               string `json:"ts"`
    InstanceID       string `json:"instance_id"`
    Attempt          int    `json:"attempt"`
    Success          bool   `json:"success"`
    Reason           string `json:"reason"`
    ElapsedMS        int    `json:"elapsed_ms"`
    Proxy            bool   `json:"proxy"`
    RotatedOnFailure bool   `json:"rotated_on_failure"`
    URL              string `json:"url"`
    BatchRegion      string `json:"batch_region"`
}

type Aggregator struct {
    Pattern      string
    pos          map[string]int64
    Success      int
    Fail         int
    PerRegion    map[string][2]int // [success, fail]
    PerInstance  map[string][2]int
    BucketSecs   int
    MaxBuckets   int
    // timeline buckets: slice of (bucketStartEpoch, succ, fail)
    Timeline     [][3]int
    bucketIndex  map[int]int // map bucketStartEpoch -> index in Timeline
}

func NewAggregator(pattern string, bucketSecs, maxBuckets int) *Aggregator {
    return &Aggregator{
        Pattern:     pattern,
        pos:         make(map[string]int64),
        PerRegion:   make(map[string][2]int),
        PerInstance: make(map[string][2]int),
        BucketSecs:  bucketSecs,
        MaxBuckets:  maxBuckets,
        Timeline:    make([][3]int, 0, maxBuckets),
        bucketIndex: make(map[int]int),
    }
}

func (a *Aggregator) bucketStart(ts time.Time) int {
    sec := ts.Unix()
    b := int(sec - (sec % int64(a.BucketSecs)))
    return b
}

func (a *Aggregator) ensureBucket(b int) {
    if _, ok := a.bucketIndex[b]; ok {
        return
    }
    a.Timeline = append(a.Timeline, [3]int{b, 0, 0})
    a.bucketIndex[b] = len(a.Timeline) - 1
    if len(a.Timeline) > a.MaxBuckets {
        // drop oldest
        oldest := a.Timeline[0][0]
        a.Timeline = a.Timeline[1:]
        // rebuild index
        a.bucketIndex = make(map[int]int, len(a.Timeline))
        for i, it := range a.Timeline {
            a.bucketIndex[it[0]] = i
        }
        // remove oldest key
        delete(a.bucketIndex, oldest)
    }
}

func (a *Aggregator) EnsureBucketsTo(now time.Time) {
    if len(a.Timeline) == 0 {
        a.ensureBucket(a.bucketStart(now))
        return
    }
    last := a.Timeline[len(a.Timeline)-1][0]
    target := a.bucketStart(now)
    for b := last + a.BucketSecs; b <= target; b += a.BucketSecs {
        a.ensureBucket(b)
    }
}

func parseTime(ts string) time.Time {
    // Expect: 2006-01-02T15:04:05 (UTC)
    // Fallback: now
    if t, err := time.Parse("2006-01-02T15:04:05", ts); err == nil {
        return t
    }
    return time.Now()
}

func (a *Aggregator) Update() {
    matches, _ := filepath.Glob(a.Pattern)
    sort.Strings(matches)
    for _, path := range matches {
        fi, err := os.Stat(path)
        if err != nil {
            delete(a.pos, path)
            continue
        }
        size := fi.Size()
        cur := a.pos[path]
        if size < cur {
            cur = 0
        }
        if size == cur {
            a.pos[path] = size
            continue
        }
        f, err := os.Open(path)
        if err != nil {
            continue
        }
        if _, err := f.Seek(cur, io.SeekStart); err != nil {
            f.Close()
            continue
        }
        br := bufio.NewReader(f)
        for {
            line, err := br.ReadBytes('\n')
            if len(line) > 0 {
                var e Entry
                if err := json.Unmarshal(trimNewlineBytes(line), &e); err == nil {
                    a.ingest(e)
                }
            }
            if err != nil {
                if err == io.EOF {
                    break
                }
                break
            }
        }
        pos, _ := f.Seek(0, io.SeekCurrent)
        a.pos[path] = pos
        f.Close()
    }
}

func (a *Aggregator) ingest(e Entry) {
    if e.Success {
        a.Success++
    } else {
        a.Fail++
    }
    if e.BatchRegion == "" { e.BatchRegion = "unknown" }
    if e.InstanceID == "" { e.InstanceID = "unknown" }
    pr := a.PerRegion[e.BatchRegion]
    pi := a.PerInstance[e.InstanceID]
    if e.Success {
        pr[0]++
        pi[0]++
    } else {
        pr[1]++
        pi[1]++
    }
    a.PerRegion[e.BatchRegion] = pr
    a.PerInstance[e.InstanceID] = pi

    bt := a.bucketStart(parseTime(e.TS))
    a.ensureBucket(bt)
    idx := a.bucketIndex[bt]
    if e.Success {
        a.Timeline[idx][1]++
    } else {
        a.Timeline[idx][2]++
    }
}

func (a *Aggregator) SetBucketSeconds(sec int) {
    if sec < 1 { sec = 1 }
    a.BucketSecs = sec
    a.Timeline = a.Timeline[:0]
    a.bucketIndex = make(map[int]int)
}

func trimNewlineBytes(b []byte) []byte {
    n := len(b)
    for n > 0 && (b[n-1] == '\n' || b[n-1] == '\r') {
        n--
    }
    return b[:n]
}

