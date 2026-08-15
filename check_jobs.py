"""
Amazon Warehouse Job Alert - checker

Checks jobsatamazon.co.uk for new warehouse job postings near a given
location and fires local + phone alerts when a new one appears.

No Amazon login or password is used anywhere in this script - job search
on jobsatamazon.co.uk is public. You only log in yourself, manually, when
you're ready to actually apply.

Run this manually first (see README.md) to confirm it works, then let
setup.ps1 schedule it to run automatically every 10 minutes.
"""

import asyncio
import json
import logging
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEN_JOBS_PATH = BASE_DIR / "seen_jobs.json"
LOG_PATH = BASE_DIR / "job_check.log"
NOTIFY_SCRIPT = BASE_DIR / "notify_popup.py"

SEARCH_URL = "https://www.jobsatamazon.co.uk/app#/jobSearch"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def log(msg: str):
    print(msg)
    logging.info(msg)


# When running in GitHub Actions (or any environment where config.json is
# public/committed to a repo), real credentials should never be written
# into that file. These environment variables - set from GitHub Actions
# Secrets - override the matching config.json field when present, so the
# committed config.json can stay full of harmless placeholders. Locally on
# your laptop, none of these env vars are set, so config.json is used as-is.
ENV_OVERRIDES = {
    "location": "JOB_LOCATION",
    "ntfy_topic": "NTFY_TOPIC",
    "twilio_account_sid": "TWILIO_ACCOUNT_SID",
    "twilio_auth_token": "TWILIO_AUTH_TOKEN",
    "twilio_from_number": "TWILIO_FROM_NUMBER",
    "twilio_to_number": "TWILIO_TO_NUMBER",
}


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    for key, env_name in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if val:
            config[key] = val
    # JOB_LOCATIONS (comma-separated) overrides the 'locations' list, e.g.
    # "Swindon,London,Manchester" - not sensitive, but handy for tweaking
    # the location list without editing config.json in a public repo.
    locations_env = os.environ.get("JOB_LOCATIONS")
    if locations_env:
        config["locations"] = [loc.strip() for loc in locations_env.split(",") if loc.strip()]
    return config


def load_seen_jobs() -> set:
    if SEEN_JOBS_PATH.exists():
        try:
            with open(SEEN_JOBS_PATH, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_seen_jobs(job_ids: set):
    with open(SEEN_JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(job_ids), f, indent=2)


async def _dismiss_overlays(page):
    """Dismiss the cookie-consent banner and the 'Guided Search' onboarding
    panel ("Tell us a little more about yourself...") if either is currently
    covering the page. Both can render a second or two after the page
    otherwise looks ready, so this actively waits for them (wait_for) rather
    than doing a single instant is_visible() check that can run too early
    and miss them entirely. Safe to call as many times as needed - it's a
    no-op if neither overlay is present."""
    for text in ["Accept all", "I consent", "Accept", "Got it"]:
        try:
            btn = page.get_by_text(text, exact=False).first
            await btn.wait_for(state="visible", timeout=1500)
            await btn.click()
            await page.wait_for_timeout(300)
            break
        except Exception:
            pass
    try:
        close_guided = page.get_by_role("button", name="Close guided search")
        await close_guided.wait_for(state="visible", timeout=1500)
        await close_guided.click()
        await page.wait_for_timeout(300)
    except Exception:
        pass


async def _search_one_location(page, location: str, radius_miles: int) -> list:
    """Runs a single location search on an already-open page and returns
    whatever job cards the site's own search response contains for it."""

    captured = {}

    async def handle_response(response):
        if response.request.method != "POST" or "graphql" not in response.url:
            return
        try:
            post_data = response.request.post_data
            if post_data and "searchJobCardsByLocation" in post_data:
                data = await response.json()
                cards = (
                    data.get("data", {})
                    .get("searchJobCardsByLocation", {})
                    .get("jobCards", [])
                )
                captured["cards"] = cards
        except Exception as e:
            captured["error"] = str(e)

    page.on("response", handle_response)
    try:
        # Belt-and-braces: the "Guided Search" onboarding panel can appear
        # at any point (not just right after the initial page load), so
        # check for it again immediately before touching the search box -
        # this is the actual point where a late-appearing overlay caused
        # failures even after dismissing it once earlier.
        await _dismiss_overlays(page)

        # Type the location and pick the matching suggestion. The site
        # sometimes also renders a second, hidden "Guided Search" input with
        # the exact same placeholder text - targeting the stable
        # #zipcode-nav-search id (the main header search box) avoids the
        # "resolved to 2 elements" ambiguity that causes entirely.
        loc_input = page.locator("#zipcode-nav-search").first
        try:
            await loc_input.click(timeout=8000)
        except Exception:
            # One more chance: an overlay may have appeared in the brief
            # window between the check above and this click. Try clearing
            # it again and retry the click once with the full timeout.
            await _dismiss_overlays(page)
            await loc_input.click()
        await loc_input.fill(location)
        await page.wait_for_timeout(1500)

        clicked = False
        options = page.locator("[role='option'], li")
        try:
            count = await options.count()
        except Exception:
            count = 0
        for i in range(count):
            opt = options.nth(i)
            try:
                text = (await opt.inner_text()).strip()
            except Exception:
                continue
            if location.lower() in text.lower() and "current location" not in text.lower():
                await opt.click()
                clicked = True
                break

        if not clicked:
            log(f"WARNING: could not find a location suggestion matching '{location}'.")
            return []

        await page.wait_for_timeout(2500)

        # Try to set the commute-distance radius. Best-effort: if the site's
        # filter panel layout doesn't match what we expect, log a warning
        # and carry on with whatever radius is already selected rather than
        # failing the whole check.
        try:
            radius_chip = page.get_by_text("miles", exact=False).first
            await radius_chip.click(timeout=3000)
            await page.wait_for_timeout(600)
            dropdown = page.get_by_text("miles", exact=False).first
            await dropdown.click(timeout=3000)
            await page.wait_for_timeout(400)
            option = page.get_by_text(f"Within {radius_miles} miles", exact=True).first
            await option.click(timeout=3000)
            await page.wait_for_timeout(400)
            apply_btn = page.get_by_text("Show", exact=False).first
            await apply_btn.click(timeout=3000)
        except Exception:
            log(f"NOTE: could not set radius to {radius_miles} miles for '{location}' - using the site's current default instead.")

        # Give the search results (and our intercepted GraphQL call) time to load.
        await page.wait_for_timeout(3000)
    finally:
        page.remove_listener("response", handle_response)

    if "error" in captured:
        log(f"WARNING: error parsing job search response for '{location}': {captured['error']}")

    return captured.get("cards", [])


async def fetch_job_cards(locations: list, radius_miles: int = 50, headless: bool = True) -> list:
    """Drives a real browser against jobsatamazon.co.uk and intercepts the
    site's own job-search response for each configured location, rather
    than guessing at an undocumented API contract. This mirrors what a real
    visitor's browser does, which is the most reliable way to get past the
    site's bot-detection layer. Results from every location are merged and
    de-duplicated by jobId - the same job can legitimately turn up from more
    than one search if its radius overlaps with a neighbouring city."""

    all_cards = {}

    async with async_playwright() as p:
        # A couple of light "look like a real visitor" touches - a realistic
        # UK locale/timezone/user-agent, and hiding the navigator.webdriver
        # flag that marks a browser as automated. Cloud CI runners (like
        # GitHub Actions) are more likely to get a bot-detection challenge
        # than a home PC, so this gives the run the best realistic chance.
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            viewport={"width": 1366, "height": 850},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        try:
            await page.goto(SEARCH_URL, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2000)

            # Dismiss the cookie-consent banner and/or the "Guided Search"
            # onboarding panel if either is covering the page. Both can
            # render with a delay (the Guided Search panel appears tied to
            # a geolocation check), so this actively waits for them rather
            # than doing a single instant check that can run too early and
            # miss them entirely.
            await _dismiss_overlays(page)

            # Make sure we're on the "All" jobs tab, not just "Recommended".
            try:
                all_tab = page.get_by_text("All", exact=True).first
                await all_tab.click(timeout=5000)
            except Exception:
                pass

            await page.wait_for_timeout(1000)

            for location in locations:
                cards = await _search_one_location(page, location, radius_miles)
                log(f"  {location}: {len(cards)} job card(s)")
                for card in cards:
                    job_id = card.get("jobId")
                    if job_id and job_id not in all_cards:
                        all_cards[job_id] = card
        except Exception:
            # Save what the browser actually saw right before it failed -
            # this is the only way to tell, after the fact, whether the real
            # site loaded normally, showed a bot-detection challenge, or
            # something else entirely. Look for these two files as workflow
            # artifacts on a failed GitHub Actions run.
            try:
                await page.screenshot(
                    path=str(BASE_DIR / "debug_screenshot.png"), full_page=True
                )
                (BASE_DIR / "debug_page.html").write_text(
                    await page.content(), encoding="utf-8"
                )
                log(
                    f"Saved failure diagnostics (debug_screenshot.png, debug_page.html). "
                    f"Page title was {await page.title()!r} at {page.url!r}."
                )
            except Exception as diag_error:
                log(f"WARNING: could not save failure diagnostics: {diag_error}")
            raise
        finally:
            await browser.close()

    return list(all_cards.values())


def job_matches_keywords(card: dict, keywords: list) -> bool:
    if not keywords:
        return True
    haystack = " ".join(
        str(card.get(k, "")) for k in ("jobTitle", "tagLine", "jobType", "employmentType")
    ).lower()
    return any(kw.lower() in haystack for kw in keywords)


def format_job_line(card: dict) -> str:
    title = card.get("jobTitle", "Job")
    loc = card.get("locationName") or card.get("city") or ""
    pay_min = card.get("totalPayRateMin")
    pay_max = card.get("totalPayRateMax")
    currency = card.get("currencyCode", "")
    pay = f" ({currency}{pay_min}-{pay_max}/hr)" if pay_min and pay_max else ""
    return f"{title} - {loc}{pay}"


def trigger_local_alert(message: str):
    """Launches a detached popup+sound process so it keeps running (and
    stays visible) even after this checker script exits. Only makes sense
    on Windows with a real desktop session - skipped automatically when
    running in a cloud/headless environment like GitHub Actions."""
    if platform.system() != "Windows":
        log("Skipping popup+sound alert (no desktop here - this isn't Windows).")
        return
    try:
        subprocess.Popen(
            [sys.executable, str(NOTIFY_SCRIPT), message],
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
        )
    except Exception as e:
        log(f"WARNING: could not launch popup notifier: {e}")


def trigger_ntfy_alert(config: dict, message: str):
    """Sends a free, instant push notification to your phone via ntfy.sh -
    no account, no cost, no message-template restrictions. Install the
    'ntfy' app (Android/iOS) and subscribe to the topic name in config.json
    to receive these."""
    topic = config.get("ntfy_topic", "")
    if not topic or "CHANGE_ME" in topic:
        log("ntfy not configured yet (config.json still has the placeholder ntfy_topic) - skipping push notification.")
        return

    url = f"https://ntfy.sh/{topic}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        method="POST",
        headers={
            "Title": "New Amazon Warehouse Job!",
            "Priority": "urgent",
            "Tags": "rotating_light",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                log("Sent push notification via ntfy.")
            else:
                log(f"WARNING: ntfy push notification returned status {resp.status}.")
    except Exception as e:
        log(f"WARNING: ntfy push notification failed: {e}")


def trigger_phone_alerts(config: dict, message: str):
    sid = config.get("twilio_account_sid", "")
    token = config.get("twilio_auth_token", "")
    from_number = config.get("twilio_from_number", "")
    to_number = config.get("twilio_to_number", "")

    if "PASTE_YOUR" in sid or "PASTE_YOUR" in token or "XXXXXXXXXX" in from_number:
        log("Twilio not configured yet (config.json still has placeholder values) - skipping call/text.")
        return

    try:
        from twilio.rest import Client
    except ImportError:
        log("WARNING: twilio package not installed - run: pip install -r requirements.txt")
        return

    client = Client(sid, token)

    # SMS and the call are tried independently - a Twilio trial-account
    # restriction blocking one (e.g. custom SMS bodies aren't allowed on
    # trial accounts) should not prevent the other from being attempted.
    try:
        client.messages.create(body=message, from_=from_number, to=to_number)
        log("Sent SMS alert via Twilio.")
    except Exception as e:
        code = getattr(e, "code", None)
        if code == 572006:
            log(
                "WARNING: SMS failed - Twilio trial accounts can't send custom "
                "text message bodies, only a fixed set of template messages. "
                "Add a small amount of credit to your Twilio account "
                "(Console -> Upgrade) to unlock custom SMS text. Skipping SMS "
                "for now; the phone call will still be attempted."
            )
        else:
            log(f"WARNING: SMS alert failed: {e}")

    try:
        say = message.replace("&", "and")
        twiml = f'<Response><Say voice="alice">{say}</Say><Pause length="1"/><Say voice="alice">{say}</Say></Response>'
        client.calls.create(twiml=twiml, from_=from_number, to=to_number)
        log("Placed phone call alert via Twilio.")
    except Exception as e:
        log(f"WARNING: phone call alert failed: {e}")


def get_locations(config: dict) -> list:
    """Supports both the newer 'locations' list (search several cities and
    merge results - use this for broad/"all jobs" coverage) and the older
    single 'location' string, for backwards compatibility."""
    locations = config.get("locations")
    if locations:
        return locations
    single = config.get("location", "")
    return [single] if single else []


async def main():
    config = load_config()
    locations = get_locations(config)
    radius = config.get("radius_miles", 50)
    keywords = config.get("keywords", [])
    headless = config.get("headless", True)
    alert_on_first_run = config.get("alert_on_first_run", False)

    if not locations:
        log("ERROR: no 'locations' (or 'location') set in config.json.")
        return

    log(f"Checking jobsatamazon.co.uk across {len(locations)} location(s) (~{radius} miles each): {', '.join(locations)}")

    # Determine "first run" from whether we've ever saved a seen-jobs file
    # before - NOT from whether it's currently empty. If an area genuinely
    # has zero jobs right now, seen_ids will still be an empty set after
    # this run, and checking len(seen_ids) == 0 would wrongly treat every
    # future run as "still the first run" - silently swallowing the very
    # first real job that ever shows up instead of alerting on it.
    is_first_run = not SEEN_JOBS_PATH.exists()
    seen_ids = load_seen_jobs()

    try:
        cards = await fetch_job_cards(locations, radius_miles=radius, headless=headless)
    except Exception as e:
        log(f"ERROR: failed to fetch job listings: {e}")
        return

    log(f"Fetched {len(cards)} unique job card(s) across all searched locations.")

    matching = [c for c in cards if job_matches_keywords(c, keywords)]
    current_ids = {c["jobId"] for c in matching if c.get("jobId")}

    new_ids = current_ids - seen_ids
    new_cards = [c for c in matching if c.get("jobId") in new_ids]

    save_seen_jobs(current_ids | seen_ids)

    if is_first_run and not alert_on_first_run:
        log(
            f"First run: recorded {len(current_ids)} existing job(s) as the baseline, "
            f"no alert sent. Future new postings will trigger alerts."
        )
        return

    if not new_cards:
        log("No new jobs since last check.")
        return

    log(f"Found {len(new_cards)} NEW job(s)!")

    # Each line already ends with " - <location>" (see format_job_line), so
    # with multiple search locations in play, the job's own location is
    # what tells you where it actually is - not the message as a whole.
    lines = [format_job_line(c) for c in new_cards[:5]]
    extra = len(new_cards) - len(lines)
    summary = "; ".join(lines)
    if extra > 0:
        summary += f"; and {extra} more"

    plural = "s" if len(new_cards) != 1 else ""
    message = f"{len(new_cards)} new Amazon warehouse job{plural}: {summary}"
    log(f"Alert message: {message}")

    trigger_local_alert(message)
    trigger_ntfy_alert(config, message)
    trigger_phone_alerts(config, message)


if __name__ == "__main__":
    asyncio.run(main())
