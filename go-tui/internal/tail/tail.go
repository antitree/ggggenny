package tail

import (
    "bufio"
    "io"
    "os"
    "path/filepath"
    "sort"
)

// Reader tails files matching a glob pattern by polling.
type Reader struct {
    Pattern string
    pos     map[string]int64
}

func NewReader(pattern string) *Reader {
    return &Reader{Pattern: pattern, pos: make(map[string]int64)}
}

// ReadNew reads and returns new lines appended since last call.
func (r *Reader) ReadNew() [][2]string {
    out := make([][2]string, 0, 128)
    matches, _ := filepath.Glob(r.Pattern)
    sort.Strings(matches)
    for _, path := range matches {
        fi, err := os.Stat(path)
        if err != nil {
            delete(r.pos, path)
            continue
        }
        size := fi.Size()
        cur := r.pos[path]
        if size < cur {
            // rotated/truncated
            cur = 0
        }
        if size == cur {
            r.pos[path] = size
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
            line, err := br.ReadString('\n')
            if len(line) > 0 {
                out = append(out, [2]string{path, trimNewline(line)})
            }
            if err != nil {
                if err == io.EOF {
                    break
                }
                break
            }
        }
        pos, _ := f.Seek(0, io.SeekCurrent)
        r.pos[path] = pos
        f.Close()
    }
    return out
}

func trimNewline(s string) string {
    if len(s) == 0 {
        return s
    }
    if s[len(s)-1] == '\n' {
        s = s[:len(s)-1]
    }
    if len(s) > 0 && s[len(s)-1] == '\r' {
        s = s[:len(s)-1]
    }
    return s
}
