"""shared-context-bridge — Real-time bidirectional context bridge between Discord Gateway & TUI CLI.

Architecture:
- When running in Discord Gateway (post_llm_call): writes conversation turn to shared JSONL tail file.
- When running in TUI CLI or Gateway (pre_llm_call): reads recent turns from opposite lane and returns `{"context": "..."}` to inject ephemeral context into current turn without touching SQLite state.db.
- Zero-lock, safe, durable cross-lane awareness.
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("hooks.shared-context-bridge")

MAX_TAIL_ENTRIES = 6
CONTEXT_DIR_NAME = "shared_context"

class BridgeConfigError(RuntimeError):
    """HERMES_HOME is missing — refuse to guess which seat we are."""


def get_context_dir():
    # 2026-08-26: this used to default to `~/.hermes-no4` when HERMES_HOME was
    # unset. A seat that forgot to export it wrote its conversation tail into
    # No.4's store and read No.4's context back — silently, with no error and
    # nothing in the log. Two faults at once: No.4 saw other seats' turns, and
    # the misconfigured seat was primed with a stranger's conversation.
    #
    # There is no safe guess here. A wrong home is worse than no bridge, so
    # raise; the caller logs it and the seat runs without cross-lane context
    # instead of corrupting someone else's.
    home = os.environ.get("HERMES_HOME", "").strip()
    if not home:
        raise BridgeConfigError(
            "HERMES_HOME is not set — shared-context-bridge refuses to guess a "
            "seat home. Export HERMES_HOME=~/.hermes-<seat> in the launcher "
            "(see hermes-ansible-playbooks/playbooks/deploy-hermes-seat-macos.yml)."
        )
    d = os.path.join(os.path.expanduser(home), CONTEXT_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d

def on_post_llm_call(session_id: str, user_message: str, assistant_response: str, platform: str = "", **kwargs):
    if not user_message or not assistant_response:
        return

    try:
        ctx_dir = get_context_dir()
    except BridgeConfigError as e:
        logger.error("shared-context-bridge disabled: %s", e)
        return
    tail_file = os.path.join(ctx_dir, "conversation_tail.jsonl")

    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform or ("cli" if not platform else platform),
        "session_id": session_id,
        "user": user_message[:400].strip(),
        "assistant": assistant_response[:400].strip()
    }

    try:
        existing = []
        if os.path.exists(tail_file):
            with open(tail_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            existing.append(json.loads(line))
                        except Exception:
                            pass
        existing.append(entry)
        existing = existing[-MAX_TAIL_ENTRIES:]

        with open(tail_file, "w", encoding="utf-8") as f:
            for item in existing:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        logger.debug("shared-context-bridge: recorded turn to tail")
    except Exception as e:
        logger.debug("shared-context-bridge post error: %s", e)

def on_pre_llm_call(session_id: str, user_message: str, platform: str = "", **kwargs):
    """Inject cross-lane context tail before agent starts thinking."""
    try:
        ctx_dir = get_context_dir()
        tail_file = os.path.join(ctx_dir, "conversation_tail.jsonl")
        if not os.path.exists(tail_file):
            return None

        current_platform = platform or "cli"
        opposite_turns = []

        with open(tail_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        # Inject turns from opposite platform or different session
                        if data.get("session_id") != session_id:
                            opposite_turns.append(data)
                    except Exception:
                        pass

        if not opposite_turns:
            return None

        # Format context injection block
        recent = opposite_turns[-3:]
        snippets = []
        for t in recent:
            p = t.get("platform", "other")
            ts = t.get("ts", "")
            u = t.get("user", "")
            a = t.get("assistant", "")
            snippets.append(f"[{ts}] [{p.upper()}] User: {u}\nAssistant: {a}")

        injected_block = (
            "\n[CROSS-LANE SHARED CONTEXT — Recent conversation from sibling channel/TUI]\n"
            + "\n---\n".join(snippets)
            + "\n[/CROSS-LANE SHARED CONTEXT]\n"
        )
        logger.info("shared-context-bridge: injected %d cross-lane turns", len(recent))
        return {"context": injected_block}
    except BridgeConfigError as e:
        logger.error("shared-context-bridge disabled: %s", e)
        return None
    except Exception as e:
        logger.debug("shared-context-bridge pre error: %s", e)
        return None

def register(ctx):
    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
