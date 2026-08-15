# Amazon Warehouse Job Alert (Swindon, 30 miles)

Checks [jobsatamazon.co.uk](https://www.jobsatamazon.co.uk/app#/jobSearch) every
10 minutes for new warehouse job postings near Swindon, and alerts you when a
new one shows up:

1. A loud repeated beep + an always-on-top popup on your laptop.
2. A free instant push notification on your phone (via [ntfy.sh](https://ntfy.sh) -
   no account, no cost).
3. Optionally, a phone call + text message via Twilio, if you set that up later
   (it requires a small amount of paid credit on Twilio's end to send custom
   content - skip it for now if you'd rather not spend anything; #1 and #2
   above are both free and need no paid account at all).

**No Amazon password, email, or OTP is ever used.** Browsing job listings on
jobsatamazon.co.uk doesn't require logging in - only *applying* does, and this
tool doesn't apply for anything. When it alerts you, you log in yourself, the
normal way, and apply.

## What's in this folder

| File | Purpose |
|---|---|
| `check_jobs.py` | The actual checker - fetches current listings, compares to last run, sends alerts if anything's new. |
| `notify_popup.py` | Shows the popup + plays the beeps. Launched automatically by `check_jobs.py`. |
| `test_alerts.py` | Fires a *test* alert on demand so you can confirm everything works before relying on it. |
| `config.json` | Your settings: location, radius, keyword filter, ntfy topic, and (optional) Twilio credentials. |
| `requirements.txt` | Python packages needed. |
| `setup.ps1` | One-time setup: installs packages, downloads the browser Playwright needs, and schedules the 10-minute check. |
| `uninstall.ps1` | Removes the scheduled task (stops automatic checking). |
| `seen_jobs.json` | Auto-created. Remembers which jobs you've already been alerted about. |
| `job_check.log` | Auto-created. Log of every check, useful for troubleshooting. |

## Setup

### 1. Install Python (if you don't have it)

Download from [python.org/downloads](https://www.python.org/downloads/) (3.10 or
newer). **During install, tick "Add python.exe to PATH."**

### 2. Set up ntfy (free push notification to your phone - no account needed)

1. Install the **ntfy** app on your phone: [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   (Android) or the App Store (iOS, search "ntfy").
2. Open the app, tap **+** (subscribe to topic), and enter this exact topic
   name (already set in `config.json` for you - a random string so strangers
   can't easily guess it and see your alerts):

   ```
   amazon-job-alert-e3d1db01e8
   ```

   If you'd rather pick your own topic name, change it in both the app and
   `config.json` (`ntfy_topic`) to match - any string works, just keep it
   non-obvious since anyone who knows the exact topic name could subscribe
   to it on the public server too.
3. That's it - no sign-up, no payment. Any message the script sends to that
   topic will pop up on your phone like a normal push notification.

### 3. (Optional, costs a small amount) Set up Twilio for phone call + text

Skip this section entirely if you don't want to spend anything - the popup
and ntfy push notification above are both free and already cover "alert me
on my phone." Come back to this later if you decide you also want an actual
ringing phone call / SMS text.

Twilio trial accounts are free to create, but won't send custom message
content (the specific job title/location) - only a fixed set of canned
messages - until you add a small amount of paid credit to the account. If
you're fine with that eventually:

1. Sign up at [twilio.com](https://www.twilio.com/).
2. In the Twilio Console, copy your **Account SID** and **Auth Token** (click
   "show" to reveal the token).
3. Go to Phone Numbers → Manage → Buy a number, and grab a free trial number.
   This is your "from" number.
4. Go to Phone Numbers → Manage → Verified Caller IDs, and verify your own
   mobile number. Trial accounts can only call/text numbers you've verified -
   this is your "to" number.
5. Add credit under Console → Upgrade to unlock custom call/text content.

Open `config.json` in Notepad and fill in the Twilio section:

```json
{
  "location": "Swindon",
  "radius_miles": 30,
  "keywords": [],
  "alert_on_first_run": false,
  "headless": true,

  "ntfy_topic": "amazon-job-alert-e3d1db01e8",

  "twilio_account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "twilio_auth_token": "your_auth_token_here",
  "twilio_from_number": "+1XXXXXXXXXX",
  "twilio_to_number": "+44XXXXXXXXXX"
}
```

Notes on the other fields:
- `keywords`: leave as `[]` to alert on *any* new job in the area (this is what
  you asked for). To narrow it, add words like `["warehouse", "delivery"]` -
  a job only has to match one.
- `alert_on_first_run`: kept `false` on purpose. The very first check just
  records whatever jobs currently exist as the starting point, without
  alerting - otherwise you'd get an alert for every job that was already
  posted before you started monitoring. Only jobs that appear *after* that
  will trigger alerts. Set it to `true` if you'd rather be alerted on
  everything immediately, including jobs already live right now.
- `headless`: leave as `true` for scheduled runs (no visible browser window).
  You can temporarily set to `false` if you want to watch it work.

**Leave the Twilio placeholder values as-is if you're skipping it** - the
popup and ntfy push notification will still work; call/text will be silently
skipped (and noted in `job_check.log`) until you fill Twilio in for real.

### 3. Run setup

Right-click this folder → "Open in Terminal" (or open PowerShell and `cd` into
it), then run:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

This installs the Python packages, downloads the browser Playwright drives,
and schedules a Windows Task ("AmazonWarehouseJobAlert") to run the check
every 10 minutes in the background - no need to keep a window open.

### 4. Test before you trust it

```powershell
.\.venv\Scripts\python.exe test_alerts.py
```

This should immediately trigger the popup+beep, a push notification on your
phone via ntfy, and (if Twilio is configured) call and text you too. Fix any
errors it prints before moving on.

```powershell
.\.venv\Scripts\python.exe check_jobs.py
```

This runs one real check against the live site and prints what it finds.
First run should say "recorded N existing jobs as baseline, no alert sent."

## Stopping it

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

This removes the scheduled task. Your `config.json` and logs stay put, so you
can re-run `setup.ps1` any time to turn it back on.

## Running it for free in the cloud instead (no laptop required)

The setup above only checks while your laptop is on. If you'd rather it keep
running even when your laptop is off, you can host it for free on **GitHub
Actions** instead - GitHub runs the check on their servers on a schedule, no
payment details needed. Trade-offs to know upfront:

- The popup+beep alert doesn't apply here (there's no screen in the cloud) -
  you'd rely on the ntfy push notification (and Twilio, if you set it up) instead.
- To stay within GitHub's free usage at a 10-minute check interval, the repo
  needs to be **public**. Nothing sensitive lives in this code - your ntfy
  topic and any Twilio credentials go into GitHub's encrypted Secrets, not
  into the code itself - but the code and its history would be visible to
  anyone.
- **Don't run both the local laptop version and this cloud version at the
  same time** - you'd get every alert twice. Pick one. If you switch to the
  cloud version, run `uninstall.ps1` locally first to stop the laptop-based
  checks.
- The cloud version starts its "have I seen this job before" memory from
  scratch, separate from whatever your laptop version already recorded. Its
  first run will just record a fresh baseline (per the `alert_on_first_run`
  setting), same as when you first set this up locally.

### Steps

1. **Create the repo.** Go to [github.com/new](https://github.com/new), name
   it something like `amazon-job-alert`, set it to **Public**, and click
   Create repository. Don't add a README/gitignore/license - leave it empty.

2. **Upload the files.** On the new repo's page, click "uploading an existing
   file", then drag in every file and folder from this project **except**
   `.venv` and `__pycache__` (you likely don't have those anyway if you're
   using a fresh copy of this folder) - that includes the `.github` folder,
   which contains the schedule that makes this work. GitHub's uploader
   preserves folder structure, so `.github/workflows/check-jobs.yml` will
   land in the right place.

3. **Blank out the ntfy topic in the uploaded config.json before committing**
   (or edit it afterward, using GitHub's built-in file editor - click the
   pencil icon on the file). Change:
   ```json
   "ntfy_topic": "amazon-job-alert-e3d1db01e8",
   ```
   to:
   ```json
   "ntfy_topic": "",
   ```
   You'll set the real value as a Secret in the next step instead, so it's
   never visible in the public repo.

4. **Add your ntfy topic as a repo Secret.** In the repo, go to Settings →
   Secrets and variables → Actions → New repository secret. Name it
   `NTFY_TOPIC`, and paste your actual topic (`amazon-job-alert-e3d1db01e8`,
   or whatever you're using) as the value. If you've set up Twilio, add
   `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, and
   `TWILIO_TO_NUMBER` as secrets the same way - otherwise skip those.

5. **Test it manually.** Go to the Actions tab, click "Check Amazon Warehouse
   Jobs" in the sidebar, click "Run workflow" → Run workflow. After it
   finishes (30-60 seconds), click into the run and check the "Check for new
   jobs" step's log - it should show the same kind of output you saw running
   `check_jobs.py` locally.

6. **That's it.** Once the manual run works, the schedule in
   `.github/workflows/check-jobs.yml` (every 10 minutes by default) takes
   over automatically - no laptop needed. To change the interval, edit the
   `cron: "*/10 * * * *"` line in that file (e.g. `*/5` for every 5 minutes)
   directly on GitHub using the pencil/edit icon, and commit the change.
   Note GitHub can delay scheduled runs by a few minutes during busy
   periods - that's a GitHub-wide limitation, not something either of us
   can fix.

## Troubleshooting

- **Check `job_check.log`** first - every run logs what it found or any error.
- If a run logs "could not find a location suggestion matching...", the site's
  UI may have changed slightly; try setting `headless` to `false` temporarily
  and running `check_jobs.py` manually to watch what happens.
- Amazon's site has bot-detection (AWS WAF) like most large sites. Checking
  every 10 minutes is a normal, low-volume usage pattern and shouldn't trip
  it, but if checks start failing consistently, space them out further (edit
  the scheduled task's repetition interval, or re-run `setup.ps1` after
  changing the interval in `New-ScheduledTaskTrigger` inside it).
- Twilio trial accounts can only call/text **verified** numbers, and calls
  open with a short trial disclaimer message before your text is read out -
  that's a Twilio trial limitation, not a bug in this script. Upgrading the
  Twilio account (adding a small amount of credit) removes it.

## A note on how this actually works

Rather than trying to reverse-engineer Amazon's internal job-search API
directly (which is guarded by bot-detection and would be fragile to
replicate with plain HTTP requests), this tool drives a real, invisible
Chromium browser (via Playwright) to the actual jobsatamazon.co.uk search
page, types in your location just like you would, and reads the job listings
straight out of the site's own response. That's slower than a raw API call
would be, but far more reliable and far less likely to get silently blocked.
