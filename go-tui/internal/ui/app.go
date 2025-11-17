package ui

import (
    "fmt"
    "os"
    "os/exec"
    "sort"
    "strings"
    "sync"
    "time"

    "github.com/gdamore/tcell/v2"
    "github.com/rivo/tview"

    "secmon/internal/metrics"
    "secmon/internal/tail"
)

type AppConfig struct {
    LogsGlob    string
    MetricsGlob string
    Refresh     time.Duration
    Bucket      int
    SnapshotDir string
    QuitAfter   time.Duration
    Debug       bool
    Headless    bool
    Simulate    bool
}

type App struct {
    cfg      AppConfig
    app      *tview.Application
    header   *tview.TextView
    logs     *tview.TextView
    stats    *tview.TextView
    timeline *tview.TextView

    logsTail *tail.Reader
    agg      *metrics.Aggregator
    paused   bool
    mu       sync.Mutex
    start    time.Time

    piaRegion string
    piaState  string
    piaIP     string
}

func NewApp(cfg AppConfig) *App {
    return &App{cfg: cfg, start: time.Now()}
}

func (a *App) Run() error {
    if a.cfg.Headless {
        return a.runHeadless()
    }
    a.app = tview.NewApplication()

    a.header = tview.NewTextView().SetDynamicColors(true).SetTextAlign(tview.AlignLeft)
    a.logs = tview.NewTextView().SetDynamicColors(false).SetScrollable(true)
    a.stats = tview.NewTextView().SetDynamicColors(true)
    a.timeline = tview.NewTextView().SetDynamicColors(true)

    a.logs.SetBorder(true).SetTitle("Logs")
    a.stats.SetBorder(true).SetTitle("Stats")
    a.timeline.SetBorder(true).SetTitle("Timeline")

    left := tview.NewFlex().SetDirection(tview.FlexRow)
    left.AddItem(a.logs, 0, 1, false)
    right := tview.NewFlex().SetDirection(tview.FlexRow)
    right.AddItem(a.stats, 0, 1, false)
    right.AddItem(a.timeline, 0, 1, false)

    mainRow := tview.NewFlex().SetDirection(tview.FlexColumn)
    mainRow.AddItem(left, 0, 3, false)
    mainRow.AddItem(right, 0, 2, false)

    root := tview.NewFlex().SetDirection(tview.FlexRow)
    root.AddItem(a.header, 1, 0, false)
    root.AddItem(mainRow, 0, 1, true)

    a.logsTail = tail.NewReader(a.cfg.LogsGlob)
    a.agg = metrics.NewAggregator(a.cfg.MetricsGlob, a.cfg.Bucket, 72)

    a.updateHeader()
    a.renderStats()
    a.renderTimeline()

    // Key bindings
    a.app.SetInputCapture(func(ev *tcell.EventKey) *tcell.EventKey {
        switch ev.Rune() {
        case 'q':
            a.app.Stop()
            return nil
        case 'p':
            a.paused = !a.paused
            return nil
        case '+':
            if a.cfg.Refresh > 200*time.Millisecond {
                a.cfg.Refresh -= 100 * time.Millisecond
            }
            return nil
        case '-':
            a.cfg.Refresh += 100 * time.Millisecond
            return nil
        case '[':
            if a.cfg.Bucket > 1 {
                a.cfg.Bucket -= 5
                if a.cfg.Bucket < 1 { a.cfg.Bucket = 1 }
                a.agg.SetBucketSeconds(a.cfg.Bucket)
            }
            return nil
        case ']':
            a.cfg.Bucket += 5
            if a.cfg.Bucket > 120 { a.cfg.Bucket = 120 }
            a.agg.SetBucketSeconds(a.cfg.Bucket)
            return nil
        case 'c':
            a.logs.Clear()
            return nil
        }
        return ev
    })

    // Tickers
    go a.loop()
    go a.pollPIA()
    if a.cfg.QuitAfter > 0 {
        go func() {
            <-time.After(a.cfg.QuitAfter)
            a.app.QueueUpdateDraw(func() { a.app.Stop() })
        }()
    }

    return a.app.SetRoot(root, true).EnableMouse(true).Run()
}

func (a *App) loop() {
    ticker := time.NewTicker(a.cfg.Refresh)
    defer ticker.Stop()
    for {
        select {
        case <-ticker.C:
            if a.paused {
                continue
            }
            // logs
            for _, pair := range a.logsTail.ReadNew() {
                name := filepathBase(pair[0])
                line := fmt.Sprintf("[%s] %s", name, pair[1])
                a.app.QueueUpdateDraw(func() {
                    fmt.Fprintln(a.logs, line)
                })
            }
            // metrics
            a.agg.Update()
            a.agg.EnsureBucketsTo(time.Now())
            a.app.QueueUpdateDraw(func() {
                a.updateHeader()
                a.renderStats()
                a.renderTimeline()
            })
        }
    }
}

func (a *App) pollPIA() {
    ticker := time.NewTicker(3 * time.Second)
    defer ticker.Stop()
    for range ticker.C {
        region := readPIA("region")
        state := readPIA("connectionstate")
        ip := readPIA("vpnip")
        a.mu.Lock()
        a.piaRegion, a.piaState, a.piaIP = region, state, ip
        a.mu.Unlock()
    }
}

func readPIA(field string) string {
    out, err := exec.Command("piactl", "get", field).CombinedOutput()
    if err != nil {
        return "na"
    }
    return strings.TrimSpace(string(out))
}

func (a *App) updateHeader() {
    a.mu.Lock()
    pia := fmt.Sprintf("pia=%s:%s:%s", a.piaRegion, a.piaState, a.piaIP)
    a.mu.Unlock()
    hdr := fmt.Sprintf(" %s | bucket=%ds | r=%.1fs  (q quit, p pause, +/- refresh, [/] bucket, c clear)", pia, a.cfg.Bucket, a.cfg.Refresh.Seconds())
    a.header.SetText(hdr)
}

func (a *App) renderStats() {
    total := a.agg.Success + a.agg.Fail
    b := &strings.Builder{}
    fmt.Fprintf(b, "Total: %d  Success: %d  Fail: %d\n", total, a.agg.Success, a.agg.Fail)
    if n := len(a.agg.Timeline); n > 0 {
        last := a.agg.Timeline[n-1]
        fmt.Fprintf(b, "Last %ds  S:%d F:%d\n", a.cfg.Bucket, last[1], last[2])
    }
    // top regions
    type kv struct{ key string; s, f int }
    arr := make([]kv, 0, len(a.agg.PerRegion))
    for k, v := range a.agg.PerRegion { arr = append(arr, kv{k, v[0], v[1]}) }
    sort.Slice(arr, func(i, j int) bool { return (arr[i].s+arr[i].f) > (arr[j].s+arr[j].f) })
    if len(arr) > 6 { arr = arr[:6] }
    fmt.Fprintln(b, "Regions:")
    for _, it := range arr {
        fmt.Fprintf(b, "  %-18s S:%4d F:%4d\n", it.key, it.s, it.f)
    }
    a.stats.SetText(b.String())
}

func (a *App) renderTimeline() {
    // Simple ASCII density chart across available width
    width := getWidth(a.timeline)
    height := getHeight(a.timeline)
    if width < 20 { width = 20 }
    if height < 4 { height = 4 }
    data := a.agg.Timeline
    if len(data) == 0 {
        a.timeline.SetText("(no data)")
        return
    }
    // limit to width-2 buckets
    maxp := width - 2
    if len(data) > maxp { data = data[len(data)-maxp:] }
    maxv := 1
    for _, p := range data {
        if v := p[1] + p[2]; v > maxv { maxv = v }
    }
    // Build two rows: density and failure markers
    chars := []rune(" .:-=+*#%@")
    line1 := make([]rune, 0, len(data))
    line2 := make([]rune, 0, len(data))
    for _, p := range data {
        v := p[1] + p[2]
        idx := int(float64(len(chars)-1) * float64(v) / float64(maxv))
        ch := chars[idx]
        if p[1] > 0 && p[2] == 0 { // success only
            ch = 'S'
        }
        line1 = append(line1, ch)
        if p[2] > 0 && p[1] == 0 { line2 = append(line2, 'F') } else { line2 = append(line2, ' ') }
    }
    b := &strings.Builder{}
    b.WriteString(string(line1))
    b.WriteByte('\n')
    b.WriteString(string(line2))
    a.timeline.SetText(b.String())
}

func getWidth(tv *tview.TextView) int {
    _, _, w, _ := tv.GetInnerRect()
    if w <= 0 { w = 80 }
    return w
}
func getHeight(tv *tview.TextView) int {
    _, _, _, h := tv.GetInnerRect()
    if h <= 0 { h = 10 }
    return h
}

func filepathBase(p string) string {
    i := strings.LastIndexAny(p, "/\\")
    if i < 0 { return p }
    return p[i+1:]
}

// Headless mode: periodically update aggregator and write snapshots without UI.
func (a *App) runHeadless() error {
    a.logsTail = tail.NewReader(a.cfg.LogsGlob)
    a.agg = metrics.NewAggregator(a.cfg.MetricsGlob, a.cfg.Bucket, 72)
    start := time.Now()
    ticker := time.NewTicker(a.cfg.Refresh)
    defer ticker.Stop()
    for {
        select {
        case <-ticker.C:
            a.agg.Update()
            a.agg.EnsureBucketsTo(time.Now())
            if a.cfg.SnapshotDir != "" { a.writeSnapshots() }
            if a.cfg.QuitAfter > 0 && time.Since(start) >= a.cfg.QuitAfter {
                return nil
            }
        }
    }
}

func (a *App) writeSnapshots() {
    // header.txt, stats.txt, timeline.txt, logs.txt (logs limited)
    // (Errors ignored — best effort.)
    pia := fmt.Sprintf("pia=%s:%s:%s", a.piaRegion, a.piaState, a.piaIP)
    _ = writeFile(a.cfg.SnapshotDir+"/header.txt", fmt.Sprintf("%s | bucket=%ds | r=%.1fs\n", pia, a.cfg.Bucket, a.cfg.Refresh.Seconds()))

    // stats
    b := &strings.Builder{}
    total := a.agg.Success + a.agg.Fail
    fmt.Fprintf(b, "Total: %d  Success: %d  Fail: %d\n", total, a.agg.Success, a.agg.Fail)
    if n := len(a.agg.Timeline); n > 0 {
        last := a.agg.Timeline[n-1]
        fmt.Fprintf(b, "Last %ds  S:%d F:%d\n", a.cfg.Bucket, last[1], last[2])
    }
    type kv struct{ key string; s, f int }
    arr := make([]kv, 0, len(a.agg.PerRegion))
    for k, v := range a.agg.PerRegion { arr = append(arr, kv{k, v[0], v[1]}) }
    sort.Slice(arr, func(i, j int) bool { return (arr[i].s+arr[i].f) > (arr[j].s+arr[j].f) })
    if len(arr) > 6 { arr = arr[:6] }
    b.WriteString("Regions:\n")
    for _, it := range arr {
        fmt.Fprintf(b, "  %-18s S:%4d F:%4d\n", it.key, it.s, it.f)
    }
    _ = writeFile(a.cfg.SnapshotDir+"/stats.txt", b.String())

    // timeline
    // shallow render as in UI
    maxp := 80
    data := a.agg.Timeline
    if len(data) > maxp { data = data[len(data)-maxp:] }
    maxv := 1
    for _, p := range data { if v := p[1]+p[2]; v > maxv { maxv = v } }
    chars := []rune(" .:-=+*#%@")
    l1 := make([]rune, 0, len(data))
    l2 := make([]rune, 0, len(data))
    for _, p := range data {
        v := p[1] + p[2]
        idx := int(float64(len(chars)-1) * float64(v) / float64(maxv))
        ch := chars[idx]
        if p[1] > 0 && p[2] == 0 { ch = 'S' }
        l1 = append(l1, ch)
        if p[2] > 0 && p[1] == 0 { l2 = append(l2, 'F') } else { l2 = append(l2, ' ') }
    }
    _ = writeFile(a.cfg.SnapshotDir+"/timeline.txt", string(l1)+"\n"+string(l2))

    // logs snapshot is not tracked in headless by default
}

func writeFile(path, content string) error {
    return os.WriteFile(path, []byte(content), 0o644)
}
