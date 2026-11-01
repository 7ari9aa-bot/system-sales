"""Shared AI string constants.

Leaf module: pure string literals, no imports. Both the customer turn
coordinator (which imports the runner) and the runtime itself import from
here, so the voice-echo sentinel and marker prefixes stay byte-identical on
the producing and matching sides — editing one cannot silently break the
echo-dedup in `AgentRunner._conversation_turns`.
"""

from __future__ import annotations

#: The fallback user-message slot for a body-less voice note whose transcript
#: did not reach the model (agents/customer/turn.py). The runtime dedup logic
#: string-matches this exact text, so both sides must share one constant.
VOICE_ECHO_SENTINEL: str = "بعت لي رسالة صوتية."

#: Prefix of the voice-note turn built by `AgentRunner._voice_turns` when a
#: transcript IS available ("[customer voice message, {status} transcript …]").
VOICE_TURN_MARKER_PREFIX: str = "[customer voice message,"

#: Prefix of the voice-note turn built by `AgentRunner._voice_turns` when a
#: transcript is NOT available ("[customer sent a voice message; …]").
VOICE_NO_TRANSCRIPT_MARKER_PREFIX: str = "[customer sent a voice message;"
