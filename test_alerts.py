"""
Run this to test your alerts (popup+sound, push notification, call/text)
WITHOUT waiting for a real job to appear. Fixes problems early instead of
during a real 3am job alert.

Usage:
    python test_alerts.py
"""

from check_jobs import load_config, trigger_local_alert, trigger_ntfy_alert, trigger_phone_alerts

if __name__ == "__main__":
    config = load_config()
    msg = "TEST ALERT - this is a test of your Amazon warehouse job notifier."
    print("Triggering local popup + sound...")
    trigger_local_alert(msg)
    print("Triggering ntfy push notification (skipped if config.json still has the placeholder topic)...")
    trigger_ntfy_alert(config, msg)
    print("Triggering Twilio call + text (skipped if config.json isn't filled in yet)...")
    trigger_phone_alerts(config, msg)
    print("Done. Check for: a popup box + beeping sound, a push notification on your phone, a text message, and a phone call.")
