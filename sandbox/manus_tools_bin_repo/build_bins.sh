#!/usr/bin/env bash
# Generates the 16 manus-* CLI executables (thin dispatchers over manus_tool_lib).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

make_bin () {
  local name="$1" func="$2"
  cat > "$DIR/$name" << EOF
#!/usr/bin/env python3
import sys
from manus_tool_lib import $func, crash_guard
sys.exit(crash_guard("$name")($func)(sys.argv[1:]))
EOF
  chmod +x "$DIR/$name"
}

make_bin manus-md-to-pdf        md_to_pdf
make_bin manus-analyze-pptx     analyze_pptx
make_bin manus-analyze-video    analyze_video
make_bin manus-render-diagram   render_diagram
make_bin manus-upload-file      upload_file
make_bin manus-webdev-logs      webdev_logs
make_bin manus-config           config
make_bin manus-heartbeat        heartbeat
make_bin manus-channel          channel
make_bin manus-export-slides    export_slides
make_bin manus-speech-to-text   speech_to_text
make_bin manus-token-local-proxy token_local_proxy
make_bin manus-mcp-cli          mcp_cli
make_bin manus-touchpoint       touchpoint
make_bin manus-touchpoint-fuse  touchpoint_fuse
make_bin manus-tools            manus_tools

echo "16 manus-* binaries ready in $DIR"
