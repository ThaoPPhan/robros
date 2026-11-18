"""Config loading and comment-preserving save of individual values."""

import re
import shutil

import yaml


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, float):
        return repr(round(v, 4))
    return str(v)


def save_values(path, section, values):
    """Rewrite `key: value` lines inside top-level `section:` of a YAML file, keeping
    comments and layout. Keys not present in the section are appended to it."""
    with open(path) as f:
        lines = f.read().split("\n")
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", ln):
            start = i
            break
    if start is None:
        raise KeyError(f"section {section!r} not found in {path}")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^[^\s#]", lines[i]):
            end = i
            break
    todo = dict(values)
    for i in range(start + 1, end):
        m = re.match(r"^(\s+)([A-Za-z_]\w*):(\s*)([^#]*?)(\s*#.*)?$", lines[i])
        if m and m.group(2) in todo:
            ind, key, sp, _, com = m.groups()
            lines[i] = f"{ind}{key}:{sp or ' '}{_fmt(todo.pop(key))}{com or ''}"
    while end > start + 1 and lines[end - 1].strip() == "":
        end -= 1
    lines[end:end] = [f"  {k}: {_fmt(v)}" for k, v in todo.items()]
    text = "\n".join(lines)
    check = yaml.safe_load(text)[section]           # validate before writing
    for k, v in values.items():
        got = check.get(k)
        if (list(got) if isinstance(got, (list, tuple)) else got) != \
                (list(v) if isinstance(v, (list, tuple)) else v) and \
                not (isinstance(v, float) and abs(float(got) - v) < 1e-3):
            raise ValueError(f"save check failed for {k}: wrote {v!r}, read {got!r}")
    shutil.copyfile(path, path + ".bak")
    with open(path, "w") as f:
        f.write(text)
