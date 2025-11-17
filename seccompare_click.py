#!/usr/bin/env python3
"""
Playwright script to visit seccompare.com and click the Compare button
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import sys
import argparse
import time
import os
import shutil
import glob
import random
import subprocess
import tempfile
import atexit
import json

# Configuration - set your target URL here
TARGET_URL = "https://www.seccompare.com"
TARGET_URL = "https://10best.usatoday.com/awards/keg-tree-genesee-brew-house-rochester-new-york/"

# PIA US regions
PIA_US_REGIONS = [
    "us-east", "us-west", "us-california", "us-texas", "us-florida",
    "us-new-york", "us-chicago", "us-atlanta", "us-denver", "us-seattle",
    "us-las-vegas", "us-silicon-valley", "us-houston", "us-washington-dc",
    "us-ohio", "us-michigan", "us-missouri", "us-indiana", "us-iowa",
    "us-wisconsin", "us-baltimore", "us-wilmington", "us-new-hampshire",
    "us-connecticut", "us-maine", "us-pennsylvania", "us-rhode-island",
    "us-vermont", "us-montana", "us-massachusetts", "us-nebraska",
    "us-new-mexico", "us-north-dakota", "us-wyoming", "us-alaska",
    "us-minnesota", "us-alabama", "us-oregon", "us-south-dakota",
    "us-idaho", "us-kentucky", "us-oklahoma", "us-south-carolina",
    "us-mississippi", "us-north-carolina", "us-kansas", "us-virginia",
    "us-west-virginia", "us-tennessee", "us-arkansas", "us-louisiana",
    "us-honolulu", "us-salt-lake-city",
]


def rotate_pia_region():
    """Connect to a random US PIA region"""
    region = random.choice(PIA_US_REGIONS)
    print(f"Rotating PIA to region: {region}")

    try:
        # Set the region
        subprocess.run(["piactl", "set", "region", region], check=True, capture_output=True)

        # Disconnect and reconnect to apply
        subprocess.run(["piactl", "disconnect"], check=True, capture_output=True)
        time.sleep(1)
        subprocess.run(["piactl", "connect"], check=True, capture_output=True)

        # Wait for connection
        print("Waiting for VPN connection...")
        for _ in range(30):  # Wait up to 30 seconds
            result = subprocess.run(["piactl", "get", "connectionstate"], capture_output=True, text=True)
            if "Connected" in result.stdout:
                # Get new IP
                ip_result = subprocess.run(["piactl", "get", "vpnip"], capture_output=True, text=True)
                print(f"Connected! VPN IP: {ip_result.stdout.strip()}")
                return True
            time.sleep(1)

        print("Warning: VPN connection timeout")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error rotating PIA region: {e}")
        return False
    except FileNotFoundError:
        print("Error: piactl not found. Is PIA installed?")
        return False


def clear_browser_cache(profile_dir):
    """Clear Firefox cache, history, and cookies while preserving certificates"""
    if not os.path.exists(profile_dir):
        return

    # Files/directories to delete (cache, history, cookies, sessions)
    patterns_to_clear = [
        "cache2",           # Browser cache
        "cookies.sqlite",   # Cookies
        "places.sqlite",    # History and bookmarks
        "formhistory.sqlite",  # Form data
        "webappsstore.sqlite",  # Local storage
        "storage",          # IndexedDB, localStorage
        "sessionstore*",    # Session data
        "*.sqlite-shm",     # SQLite temp files
        "*.sqlite-wal",     # SQLite write-ahead log
    ]

    for pattern in patterns_to_clear:
        full_pattern = os.path.join(profile_dir, pattern)
        for path in glob.glob(full_pattern):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(f"Cleared: {os.path.basename(path)}")
            except Exception as e:
                print(f"Warning: Could not clear {path}: {e}")


def apply_firefox_prefs(profile_dir: str, prefs: dict):
    """Ensure Firefox user.js contains the given preferences before startup."""
    try:
        os.makedirs(profile_dir, exist_ok=True)
        user_js_path = os.path.join(profile_dir, "user.js")
        existing = []
        if os.path.exists(user_js_path):
            with open(user_js_path, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.readlines()

        # Filter out any existing lines for our keys
        def is_line_for_key(line, key):
            return f'user_pref("{key}",' in line

        filtered = [ln for ln in existing if not any(is_line_for_key(ln, k) for k in prefs.keys())]

        with open(user_js_path, "w", encoding="utf-8") as f:
            for ln in filtered:
                f.write(ln)
            for k, v in prefs.items():
                if isinstance(v, bool):
                    js_val = "true" if v else "false"
                elif isinstance(v, (int, float)):
                    js_val = str(v)
                else:
                    js_val = '"' + str(v).replace('"', '\\"') + '"'
                f.write(f'user_pref("{k}", {js_val});\n')
        print(f"Applied Firefox prefs to {user_js_path}: {', '.join(prefs.keys())}")
    except Exception as e:
        print(f"Warning: Failed to apply Firefox prefs: {e}")


def run_once(args, profile_dir, attempt_num: int = 1):
    """Run a single attempt. Returns (success: bool, reason: str)."""
    with sync_playwright() as p:
        print("Launching Firefox with persistent profile...")
        print(f"Profile directory: {profile_dir}")

        launch_options = {
            "headless": args.headless,
            "viewport": {"width": 1280, "height": 720},
            "ignore_https_errors": True,
        }

        if args.proxy:
            launch_options["proxy"] = {"server": "http://127.0.0.1:8080"}
            print("Using proxy: http://127.0.0.1:8080")

        context = p.firefox.launch_persistent_context(profile_dir, **launch_options)

        page = context.pages[0] if context.pages else context.new_page()
        # Prefer shorter defaults to react faster
        try:
            page.set_default_timeout(6000)
            page.set_default_navigation_timeout(15000)
        except Exception:
            pass

        try:
            print(f"Navigating to {TARGET_URL}...")
            page.goto(TARGET_URL, timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            print(f"Page loaded: {page.title()}")

            # Skipping pre-click screenshot to optimize speed

            button_selector = "button.JYo3d8rUPG8-"
            print(f"Looking for button: {button_selector}")

            try:
                page.wait_for_selector(button_selector, timeout=6000)
                print("Button found!")
            except PlaywrightTimeout:
                print(f"ERROR: Button '{button_selector}' not found after 6 seconds")
                print("\nDebugging info:")
                print(f"Current URL: {page.url}")
                print(f"Page title: {page.title()}")
                print("\nAll buttons on page:")
                buttons = page.locator("button").all()
                for i, btn in enumerate(buttons[:15]):
                    text = btn.inner_text().strip()[:50] if btn.inner_text() else ""
                    classes = btn.get_attribute("class") or ""
                    print(f"  {i+1}. text='{text}' class='{classes}'")
                return False, "button_not_found"

            compare_button = page.locator(button_selector).first
            url_before = page.url

            print("Clicking Compare button...")
            compare_button.click()
            print("Waiting for response...")

            changes_detected = False

            try:
                page.wait_for_url(lambda url: url != url_before, timeout=3000)
                print(f"URL changed: {url_before} -> {page.url}")
                changes_detected = True
            except PlaywrightTimeout:
                pass

            print("\n--- RESULTS ---")
            print(f"Final URL: {page.url}")
            print(f"Final Title: {page.title()}")

            # Strict success criteria: page contains "Thanks for voting!" (case-insensitive)
            success_text = "thanks for voting!"
            changes_detected = False

            # Strategy 1: Text locator
            try:
                page.get_by_text("Thanks for voting!", exact=False).first.wait_for(state="visible", timeout=6000)
                print("Detected success text via locator: 'Thanks for voting!'")
                changes_detected = True
            except PlaywrightTimeout:
                pass

            # Strategy 2: Poll body innerText
            if not changes_detected:
                try:
                    page.wait_for_function(
                        "text => document.body && document.body.innerText.toLowerCase().includes(text)",
                        success_text,
                        timeout=6000,
                    )
                    print("Detected success text via body innerText check.")
                    changes_detected = True
                except PlaywrightTimeout:
                    pass

            if changes_detected:
                print("\nSUCCESS: Voting appears to have worked (found 'Thanks for voting!').")
                return True, "success_text_detected"
            else:
                # Take an after-click screenshot only on failure to save time
                after_path = f"after_click_attempt{attempt_num}.png"
                try:
                    page.screenshot(path=after_path)
                    print(f"Screenshot saved: {after_path}")
                except Exception:
                    pass
                # Capture HTML for debugging ideal selector
                html_path = f"page_attempt{attempt_num}.html"
                try:
                    html = page.content()
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"Saved page HTML for debugging: {html_path}")
                except Exception as he:
                    print(f"Warning: Failed to save HTML: {he}")

                print("\nFAILURE: Did not detect 'Thanks for voting!' after clicking.")
                return False, "no_success_text"

        except PlaywrightTimeout as e:
            print(f"Timeout error: {e}")
            err_path = f"error_screenshot_attempt{attempt_num}.png"
            page.screenshot(path=err_path)
            print(f"Saved error screenshot: {err_path}")
            return False, "timeout_exception"
        except Exception as e:
            print(f"Error: {e}")
            err_path = f"error_screenshot_attempt{attempt_num}.png"
            try:
                page.screenshot(path=err_path)
                print(f"Saved error screenshot: {err_path}")
            except Exception:
                pass
            return False, "generic_exception"
        finally:
            print("\nClosing browser...")
            context.close()


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Visit seccompare.com and click Compare button")
    parser.add_argument("--proxy", action="store_true", help="Use HTTP proxy at 127.0.0.1:8080")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--clear-cache", action="store_true", help="Clear browser cache and history on startup")
    parser.add_argument("--rotate-ip", action="store_true", help="Rotate PIA VPN to random US region (requires --proxy)")
    parser.add_argument("--max-attempts", type=int, default=10, help="Maximum number of attempts before stopping (default: 10)")
    parser.add_argument("--ephemeral", action="store_true", help="Use a temporary Firefox profile for this run (good for multiple parallel instances)")
    parser.add_argument("--disable-webspeech", action="store_true", help="Disable Firefox media.webspeech.synth.enabled to reduce CPU usage")
    parser.add_argument("--metrics-file", type=str, default=None, help="Path to a JSONL file to append per-attempt metrics")
    parser.add_argument("--instance-id", type=str, default=None, help="Label to identify this process in metrics (e.g., instance number)")
    parser.add_argument("--batch-region", type=str, default=None, help="PIA region label for this batch (recorded in metrics)")
    args = parser.parse_args()

    # Determine profile directory
    if args.ephemeral:
        profile_dir = tempfile.mkdtemp(prefix="ff-profile-")
        print(f"Using ephemeral Firefox profile: {profile_dir}")

        def _cleanup_profile():
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
                print(f"Cleaned up ephemeral profile: {profile_dir}")
            except Exception as e:
                print(f"Warning: Failed to clean ephemeral profile {profile_dir}: {e}")

        atexit.register(_cleanup_profile)
    else:
        profile_dir = "./burp"

    if args.rotate_ip:
        if not args.proxy:
            print("Warning: --rotate-ip requires --proxy flag, skipping IP rotation")
        else:
            rotate_pia_region()

    successes = 0
    failures = 0

    def attempt_loop(max_attempts: int):
        nonlocal successes, failures
        attempt = 0
        while True:
            attempt += 1
            if max_attempts != 0 and attempt > max_attempts:
                break

            if max_attempts == 0:
                print(f"\n===== Attempt {attempt} of ∞ =====")
            else:
                print(f"\n===== Attempt {attempt} of {max_attempts} =====")

            # Clear cache on each loop if requested
            if args.clear_cache:
                print("Clearing browser cache and history...")
                clear_browser_cache(profile_dir)

            # Apply requested Firefox prefs before launching browser
            if args.disable_webspeech:
                apply_firefox_prefs(profile_dir, {"media.webspeech.synth.enabled": False})

            t0 = time.time()
            ok, reason = run_once(args, profile_dir, attempt)
            elapsed_ms = int((time.time() - t0) * 1000)

            # Prepare metrics payload
            payload = None
            if args.metrics_file:
                payload = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                    "instance_id": args.instance_id,
                    "attempt": attempt,
                    "success": bool(ok),
                    "reason": reason,
                    "elapsed_ms": elapsed_ms,
                    "proxy": bool(args.proxy),
                    "rotated_on_failure": False,
                    "url": TARGET_URL,
                }

            if ok:
                successes += 1
            else:
                failures += 1
                # Rotate PIA region on failure if requested
                if args.rotate_ip:
                    if not args.proxy:
                        print("Warning: Cannot rotate IP without --proxy; skipping rotation.")
                    else:
                        rotate_pia_region()
                        if payload is not None:
                            payload["rotated_on_failure"] = True

            # Write metrics if requested
            if args.metrics_file and payload is not None:
                try:
                    # Add batch-level fields
                    payload["batch_region"] = args.batch_region
                    with open(args.metrics_file, "a", encoding="utf-8") as mf:
                        mf.write(json.dumps(payload) + "\n")
                except Exception as me:
                    print(f"Warning: Failed to write metrics: {me}")

            # Small pause between attempts to avoid hammering
            time.sleep(0.5)

    attempt_loop(args.max_attempts)

    if successes == 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
