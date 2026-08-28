# The demos, one JSON file per demo

What the **Demos** menu offers. A demo is a recipe plus the sentence that says
what to watch for while it runs — the prose is the point, and a demo that only
produced a shape would teach nothing.

These files are read at startup. In a delivered build this directory sits **next
to the executable**, so changing a duration here and restarting is the whole
edit-and-see loop: no checkout, no toolchain.

## The format

```json
{
  "schema_version": 1,
  "key": "lift_off",
  "title": "Naive lift-off",
  "summary": "one line, the menu tooltip",
  "watch_for": "what to look at, and what its absence would look like",
  "grid": {"origin": [0, 0], "spacing": 1.0, "shape": [241, 301], "axes": ["y", "x"]},
  "steps": [
    {
      "step_id": "resist.spin_coat_ideal",
      "params": {"material": "resist", "thickness": 90.0},
      "note": "why this number is this number"
    }
  ]
}
```

`note` is optional and is for whoever opens the file: it is where the reason for
a number lives, next to the number.

## Rules

- **A field this version does not know is an error**, not a silently ignored key.
  These files are written by hand, and a `durration` that is quietly dropped is a
  demo that does the wrong thing without saying so.
- **A file that does not parse costs that demo and nothing else.** The menu still
  opens, and `--version` lists what was skipped and why.
- **The filename orders the menu**, which is why the shipped five are numbered. A
  file you add lands after them. A file whose `key` matches a shipped one
  *replaces* it and keeps its position.
- **`step_id` and `params` belong to the process registry**, not to this file. Run
  a recipe with an unknown step and it fails at that step, loudly — a demo is not
  a place where a typo becomes a new process.
- **No physics here.** Rates live in `../materials/`. A demo that hard-coded its
  own numbers would keep working while the library it illustrates drifted away
  from it.
