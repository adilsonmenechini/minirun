---
name: example
description: "Template command — reference for creating new workspace commands"
type: shell
---
# Example Command

This is a reference command. Copy this file to create a new command.

```sh
#!/usr/bin/env bash
# Usage: ./example.sh [--name NAME]

set -euo pipefail

NAME="${1:-world}"

echo "Hello, ${NAME}!"
echo "This is an example command from workspace/commands/"
echo "Total arguments: $#"
```
