import re

STOP = set(
    (
        "a an the of to in on for and or is are was were "
        "be been what which who whom how when where why do does did can "
        "could should would will with within at by from as that this these those "
        "it its i you we they me my our your their about into than "
        "then there tell give explain please must may per after before "
    ).split()
)


def tokens(text: str, drop_stop: bool = True) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        if drop_stop and t in STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def coverage(query: str, text: str) -> float:
    q = set(tokens(query))
    if not q:
        return 0.0
    return len(q & set(tokens(text))) / len(q)
