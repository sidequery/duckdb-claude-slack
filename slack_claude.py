# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "slack-bolt",
#     "duckdb==1.4.2",
# ]
# ///
"""
Slack bot that uses DuckDB ACP extension to call Claude Code.

Setup:
1. Create a Slack app at https://api.slack.com/apps
2. Enable Socket Mode and get an App-Level Token (xapp-...)
3. Add Bot Token Scopes: app_mentions:read, chat:write, channels:history, groups:history
4. Install to workspace and get Bot User OAuth Token (xoxb-...)
5. Subscribe to bot events: app_mention, message.channels, message.groups

Environment variables:
    SLACK_BOT_TOKEN  - Bot User OAuth Token (xoxb-...)
    SLACK_APP_TOKEN  - App-Level Token for Socket Mode (xapp-...)

Usage:
    uv run slack_claude.py
"""

import io
import os
import re
import duckdb
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


def query_claude(prompt: str) -> tuple[str, str | None]:
    """Query Claude via DuckDB ACP extension. Returns (message, csv_content)."""
    conn = duckdb.connect()

    # Install and load the extension
    conn.execute("INSTALL acp FROM community;")
    conn.execute("LOAD acp;")

    try:
        result = conn.execute(f"CLAUDE {prompt};")
        columns = [col[0] for col in result.description]
        rows = result.fetchall()

        if not rows:
            return "_No results_", None

        # Build CSV
        csv_lines = [",".join(columns)]
        for row in rows:
            csv_lines.append(",".join(str(v) if v is not None else "" for v in row))
        csv_content = "\n".join(csv_lines)

        # Summary message
        msg = f"Returned {len(rows)} row(s), {len(columns)} column(s)"
        return msg, csv_content

    except Exception as e:
        return f"*Error:* `{e}`", None
    finally:
        conn.close()


# Initialize app
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))


@app.event("app_mention")
def handle_mention(event, say, client):
    """Handle @mentions of the bot."""
    text = event.get("text", "")
    channel = event["channel"]
    ts = event["ts"]
    thread_ts = event.get("thread_ts", ts)  # Use existing thread or start new one

    # React with eyes emoji
    try:
        client.reactions_add(channel=channel, timestamp=ts, name="eyes")
    except Exception:
        pass  # Missing scope, ignore

    # Remove the bot mention from the text
    prompt = re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()

    if not prompt:
        say(
            text="Please include a question or query after mentioning me.",
            channel=channel,
            thread_ts=thread_ts,
        )
        return

    # Acknowledge immediately
    ack_response = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Working on: _{prompt}_",
    )

    # Query Claude via DuckDB
    msg, csv_content = query_claude(prompt)

    # Update with result
    client.chat_update(
        channel=channel,
        ts=ack_response["ts"],
        text=f"*Query:* _{prompt}_\n\n{msg}",
    )

    # Upload CSV if we have results
    if csv_content:
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            content=csv_content,
            filename="results.csv",
            title="Query Results",
        )


@app.event("message")
def handle_message(event, say, client, logger):
    """Handle direct messages or channel messages (if bot is invited)."""
    # Skip bot messages and messages with subtypes (edits, etc.)
    if event.get("bot_id") or event.get("subtype"):
        return

    # Skip if this is a mention (handled separately)
    text = event.get("text", "")
    if re.search(r"<@[A-Z0-9]+>", text):
        return

    channel = event["channel"]
    ts = event["ts"]
    thread_ts = event.get("thread_ts", ts)

    prompt = text.strip()
    if not prompt:
        return

    # Acknowledge immediately
    ack_response = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Working on: _{prompt}_",
    )

    # Query Claude via DuckDB
    msg, csv_content = query_claude(prompt)

    # Update with result
    client.chat_update(
        channel=channel,
        ts=ack_response["ts"],
        text=f"*Query:* _{prompt}_\n\n{msg}",
    )

    # Upload CSV if we have results
    if csv_content:
        client.files_upload_v2(
            channel=channel,
            thread_ts=thread_ts,
            content=csv_content,
            filename="results.csv",
            title="Query Results",
        )


if __name__ == "__main__":
    print("Starting Slack Claude bot...")
    handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
    handler.start()
