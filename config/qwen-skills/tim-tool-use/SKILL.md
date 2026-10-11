---
name: tim-tool-use
description: How to use the TIM worker tools efficiently before proposing a patch.
metadata:
  tim-applies-to: "tool-loop"
---

# Working with the tools

You have a small step budget. Use it to understand, then submit.

1. Read the failing or required test first (`read_file`), then the code it imports.
2. Use `search_code` to find where a name is defined or used. Search for an exact
   identifier such as `def build_task` rather than a sentence.
3. Run `run_required_tests` once to see the current failure, if the task does not say it.
4. Draft the patch and call `check_patch`. Fix every problem it reports.
5. Call `submit_patch` with the same patch. This ends your turn.

Do not reread a file you already have. Do not call tools in circles; if you are stuck,
submit your best patch and let the tests answer.
