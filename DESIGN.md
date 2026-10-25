# Design and acceptance

Target: a maintainer curates a directory of shipped vendor assets and needs a
reviewable notice file. The TOML manifest is the human-owned inventory; the
JSON lock records exact bytes and normalized metadata; the generated bundle is
a deterministic derivative. None is automatically treated as legal approval.

Pipeline: strict schema → root-contained file validation → recursive coverage →
streamed asset hashing / bounded notice reads → receipt comparison → optional
bundle byte comparison or publication. Paths and component IDs sort output.
Source references are never interpreted as executable URLs.

Acceptance tests exercise the installed CLI, byte drift in both roles,
uncovered hidden/nested files, stale bundle detection, refusal to overwrite
inputs, malformed schemas, duplicate JSON keys, resource limits and links.
Temporary output is removed on success or failure. Check performs no writes.
Symlink creation is tested on hosts that permit it, with Linux CI providing
the required filesystem coverage.

Independent review focus: no automatic license choice; no omitted inventory
entries; no input can be selected as output; pin changes must fail before
render; raw notice bytes survive output. Trust boundary: a local filesystem
that is not being maliciously mutated during traversal.
