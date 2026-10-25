import re

MAX_LEN = 1000
BLOCK = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|rules)",
    r"disregard .{0,30}(instructions|rules|policy)",
    r"reveal .{0,30}(system prompt|api key|secret|password)",
    r"you are now (dan|an? unrestricted)",
    r"jailbreak",
]


def check_input(text: str) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if not text or not text.strip():
        return False, "Empty question."
    if len(text) > MAX_LEN:
        return False, f"Question exceeds {MAX_LEN} characters."
    low = text.lower()
    for pat in BLOCK:
        if re.search(pat, low):
            return False, "Blocked by safety guardrail (possible prompt injection)."
    return True, ""
