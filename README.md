# ggggenny

An automated browser clicking tool that can repeatedly click on web pages for you. Useful for voting contests, performance testing, and automation tasks.

## What You Need Before Starting

### For Linux Users
- Python (version 3.8 or newer)
- Firefox web browser

### For Windows Users
- Python (download from https://www.python.org/downloads/)
- Firefox web browser

## Setup Instructions

### Step 1: Download This Project

Open your terminal (Linux) or Command Prompt (Windows) and type:

```
git clone <repository-url>
cd ggggenny
```

If you downloaded a ZIP file instead, extract it and open a terminal in that folder.

### Step 2: Install Required Software

**On Linux**, type these commands one at a time:

```
pip3 install playwright
pip3 install textual rich matplotlib
playwright install firefox
mkdir -p metrics
```

**On Windows**, type these commands one at a time:

```
pip install playwright
pip install textual rich matplotlib
playwright install firefox
mkdir metrics
```

The last command (`playwright install firefox`) downloads the browser automation tools. This may take a few minutes.

### Step 3: Verify Installation

Type this command to make sure everything is working:

```
python3 seccompare_click.py --help
```

On Windows, you might need to use `python` instead of `python3`:

```
python seccompare_click.py --help
```

You should see a list of options. If you see an error, go back and make sure Step 2 completed successfully.

## How to Use

### Basic Usage: Run the Clicker

This will open a browser and click on the target page 10 times:

**Linux:**
```
python3 seccompare_click.py --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

**Windows:**
```
python seccompare_click.py --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

You will see a Firefox browser window open and the script will automatically navigate and click.

### Run Without Showing the Browser Window

Add `--headless` to run in the background (no visible browser):

**Linux:**
```
python3 seccompare_click.py --headless --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

**Windows:**
```
python seccompare_click.py --headless --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

### Use a Fresh Browser Each Time

Add `--ephemeral` to start with a clean browser profile (no cookies or history):

**Linux:**
```
python3 seccompare_click.py --headless --ephemeral --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

**Windows:**
```
python seccompare_click.py --headless --ephemeral --max-attempts 10 --metrics-file metrics/results.jsonl --instance-id test1
```

### Understanding the Options

| Option | What it Does |
|--------|--------------|
| `--headless` | Runs the browser invisibly in the background |
| `--ephemeral` | Uses a fresh browser profile each time (no saved cookies) |
| `--max-attempts 10` | Stops after 10 clicks (change the number as needed) |
| `--metrics-file metrics/results.jsonl` | Saves results to this file |
| `--instance-id test1` | Gives this run a name (useful when running multiple) |
| `--proxy` | Routes traffic through a proxy server |
| `--clear-cache` | Clears browser cache between each attempt |

## Viewing Your Results

### See a Summary

After running, you can see statistics about your clicks:

**Linux:**
```
python3 analyze_metrics.py --input metrics/results.jsonl
```

**Windows:**
```
python analyze_metrics.py --input metrics/results.jsonl
```

This shows you how many clicks succeeded, failed, and average timing.

### Create a Chart

To create a visual chart of your results:

**Linux:**
```
python3 analyze_metrics.py --input metrics/results.jsonl --out my_results.png
```

**Windows:**
```
python analyze_metrics.py --input metrics/results.jsonl --out my_results.png
```

This creates an image file called `my_results.png` that you can open to see your results graphically.

## Watch Progress in Real-Time

While the clicker is running, you can monitor it in another terminal window:

**Linux:**
```
python3 textual_monitor.py --metrics "metrics/*.jsonl"
```

**Windows:**
```
python textual_monitor.py --metrics "metrics/*.jsonl"
```

This opens a dashboard showing live statistics. Press `q` to quit the monitor.

## Generate Test Data (Demo Mode)

Want to see how the monitoring tools work without actually clicking? Generate fake data:

**Linux:**
```
python3 gen_metrics.py --output metrics/demo.jsonl --duration 60 --rate 2.0
```

**Windows:**
```
python gen_metrics.py --output metrics/demo.jsonl --duration 60 --rate 2.0
```

This creates 60 seconds worth of fake click data. Then you can view it with the monitor or analyzer.

## Troubleshooting

### "Command not found" or "python3 not recognized"

- **Windows**: Try using `python` instead of `python3`
- **Linux**: Install Python with `sudo apt install python3` (Ubuntu/Debian) or `sudo dnf install python3` (Fedora)

### "playwright: command not found"

After installing playwright with pip, you may need to restart your terminal. Or try:

**Linux:**
```
python3 -m playwright install firefox
```

**Windows:**
```
python -m playwright install firefox
```

### Browser doesn't open or crashes

1. Make sure Firefox is installed on your computer
2. Try reinstalling playwright browsers:
   ```
   playwright install firefox
   ```
3. Check you have enough free disk space

### "No module named 'playwright'"

The required software didn't install properly. Try again:

**Linux:**
```
pip3 install --upgrade playwright
```

**Windows:**
```
pip install --upgrade playwright
```

### Results file is empty or missing

Make sure the `metrics` folder exists:

**Linux:**
```
mkdir -p metrics
```

**Windows:**
```
mkdir metrics
```

## Files in This Project

| File | Purpose |
|------|---------|
| `seccompare_click.py` | The main clicking tool |
| `analyze_metrics.py` | Shows statistics and creates charts from results |
| `textual_monitor.py` | Live dashboard to watch progress |
| `gen_metrics.py` | Creates fake test data for demos |
| `tui_monitor.py` | Alternative live dashboard (simpler interface) |
| `metrics/` | Folder where results are saved |

## Need Help?

If something isn't working:

1. Make sure you followed all the setup steps
2. Check the Troubleshooting section above
3. Try running with `--help` to see all available options
4. Look for error messages - they often tell you what's wrong
