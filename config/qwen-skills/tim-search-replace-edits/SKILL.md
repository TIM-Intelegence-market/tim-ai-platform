---
name: tim-search-replace-edits
description: How to write search/replace edits that TIM can apply without guessing.
metadata:
  tim-applies-to: "always"
---

# Search/replace edits

For an existing file send `edits` instead of the whole file:

```json
{"path": "src/example.py", "edits": [
  {"search": "def total(items):\n    return sum(items)\n",
   "replace": "def total(items):\n    return sum(item.amount for item in items)\n"}
]}
```

- Copy `search` character for character from the file content you were shown,
  including indentation and line breaks.
- `search` must appear exactly once in the file. Add a neighbouring line if it is not unique.
- Keep each edit small: the function or block you change, not the whole file.
- Edits apply in order; a later edit sees the result of the earlier ones.
- New files (shown as MISSING) need full `content`, not edits.
- Do not send `content` and `edits` for the same file.
