package main

import (
    "flag"
    "fmt"
    "time"

    "secmon/internal/ui"
)

func main() {
    var logs, metrics string
    var refresh float64
    var bucket int
    var snapshot string
    var quitAfter float64
    var debug bool
    var headless bool
    var simulate bool

    flag.StringVar(&logs, "logs", "instance_*.log", "Glob for instance logs")
    flag.StringVar(&metrics, "metrics", "metrics/*.jsonl", "Glob for metrics files")
    flag.Float64Var(&refresh, "refresh", 1.0, "Refresh interval seconds")
    flag.IntVar(&bucket, "bucket", 10, "Timeline bucket size seconds")
    flag.StringVar(&snapshot, "snapshot-dir", "", "Write snapshots to this dir (optional)")
    flag.Float64Var(&quitAfter, "quit-after", 0, "Exit after N seconds (optional)")
    flag.BoolVar(&debug, "debug", false, "Enable debug logs (stderr)")
    flag.BoolVar(&headless, "headless", false, "Run in headless snapshot mode")
    flag.BoolVar(&simulate, "simulate", false, "Generate synthetic metrics for demo")
    flag.Parse()

    cfg := ui.AppConfig{
        LogsGlob:    logs,
        MetricsGlob: metrics,
        Refresh:     time.Duration(refresh*1000) * time.Millisecond,
        Bucket:      bucket,
        SnapshotDir: snapshot,
        QuitAfter:   time.Duration(quitAfter*1000) * time.Millisecond,
        Debug:       debug,
        Headless:    headless,
        Simulate:    simulate,
    }

    app := ui.NewApp(cfg)
    if err := app.Run(); err != nil {
        fmt.Println("error:", err)
    }
}

