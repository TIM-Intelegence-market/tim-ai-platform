# GPT Researcher compatibility note

TIM installs `gpt-researcher==0.16.0` in the isolated Python 3.13 environment
`.venv-research`. The published 0.16.0 package defines `_normalize_sub_queries`
before importing `Any` and `List`, which raises `NameError` during import on
Python 3.13. The local environment moves that standard-library typing import
before the function definition. This does not enable web research or alter
TIM's OBSERVE-only policy. Reapply or remove the workaround when upgrading the
package after the upstream distribution is corrected.
