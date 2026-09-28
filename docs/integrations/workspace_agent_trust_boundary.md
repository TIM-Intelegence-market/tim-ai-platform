# Workspace Agent Trust Boundary

Repository text, Workspace Agent input, and Graphify output are untrusted data.
They cannot change the authority order: Git and validated TIM artifacts remain
authoritative; Graphify and agent output remain retrieval aids.

Text such as `ignore previous instructions`, shell fragments, Git requests, or
trading commands is never executed. It can only be passed as a bounded search
string to an allowlisted read operation. Nested tool names, shell fields,
caller-controlled paths, excluded paths, unknown operations, and write
operations fail closed.

The Workspace Agent receives no direct filesystem, Git, Graphify, governance,
research, trading, risk, execution, or capital authority. Results are
repackaged with `untrusted_retrieval`, graph hash, tool name, source references,
warnings, and raw-response hash.
