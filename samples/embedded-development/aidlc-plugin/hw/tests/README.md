# Tests

`verify.sh` validates the plugin with the official AI-DLC plugin tools (`aidlc-plugin-validate`, `aidlc-plugin-test`).
On Kiro harnesses it then builds the plugin, composes it into a copy of an install, and runs `check_compose.py`,
which compares the install before and after: the new stages, their edges, scopes and order; where each step is
spliced into a core stage; and that every core stage is unchanged outside the plugin's blocks. Tests stay in this
directory: compose copies `tools/` into every install.
