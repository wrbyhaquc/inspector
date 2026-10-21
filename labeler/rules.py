"""Screen rules run on a frame (weak labels for training, a second opinion while scripts run).

Two kinds:
  generic   color ratio / reference images, configured on the state page (labeler/generic.py)
  provided  rule types a project's plugin registers (kind "rule"), as a provider object:
              version                       bump when its answers change (invalidates the rule cache)
              configure(schema, data_root)  take regions / thresholds from the state definitions
              states()                      the state ids it answers
              label(img)                    -> {"values": {state id: value or None}, "scores": {...}, "flags": [...]}
              hidden(schema)                optional: {state id: (flags meaning "not visible", flags needed with
                                            them or None)} -> the model learns the "hidden" class from them
              live_answer(sid, raw)         the answer scripts may rely on, from a label_frame() record (it may be
                                            stricter than the label, e.g. not sure where a training label guesses)
label_frame(img) runs the providers first (generic rules may be gated on their answers), then the generic rules.
The platform knows no rule by name."""
ENGINE = None          # generic rules of the configured schema
PROVIDERS = []


def _providers():
    from project.plugins import registry
    seen, out = set(), []
    for p in registry().all("rule").values():
        if hasattr(p, "label") and id(p) not in seen:
            seen.add(id(p))
            out.append(p)
    return out


def configure(schema, data_root=None):
    global ENGINE, PROVIDERS
    from . import generic
    ENGINE = generic.Engine(schema, data_root) if data_root else None
    PROVIDERS = _providers()
    for p in PROVIDERS:
        p.configure(schema, data_root)


def version():
    """Changes when any provider's rules change (part of the rule cache key, with the rules' settings)."""
    return ",".join(str(p.version) for p in PROVIDERS) or "0"


def provided_ids():
    """State ids answered by plugin-provided rules."""
    return set().union(*(p.states() for p in PROVIDERS)) if PROVIDERS else set()


def label_frame(img, generic=True):
    """img: RGB frame of the coordinate space -> {state id: value, ..., "flags": [...], "scores": {...}}.
    generic=False: only the provided rules (not the states made on the state page)."""
    out, scores, flags = {}, {}, []
    for p in PROVIDERS:
        r = p.label(img)
        out.update(r["values"])
        scores.update(r.get("scores") or {})
        flags.extend(r.get("flags") or [])
    if generic and ENGINE and ENGINE.states:
        values, gscores, gflags = ENGINE.label(img, dict(out))
        out.update(values)
        scores.update(gscores)
        flags.extend(gflags)
    return {**out, "flags": flags, "scores": scores}


def live_answer(sid, raw):
    """A state's answer from a label_frame() record, as the live rule gives it (a provider may be stricter)."""
    for p in PROVIDERS:
        if sid in p.states():
            return p.live_answer(sid, raw)
    return raw.get(sid)


def hidden(schema):
    """{state id: (flags meaning "not visible", flags that must come with them or None)} from the providers."""
    out = {}
    for p in _providers():
        if hasattr(p, "hidden"):
            out.update(p.hidden(schema))
    return out
