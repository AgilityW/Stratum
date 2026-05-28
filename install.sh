#!/bin/bash
# install.sh — Hermes Skill Installer
#
# Usage:
#   ./install.sh          # Distribution: cp → ~/.hermes/skills/
#   ./install.sh --dev    # Development: symlink raw skills/ directly
#
# Path resolution: ${OUTPUT_DIR}, ${HEALTH_DATA_DIR}, ${CHROME_PATH} in
# SKILL.md files are notation for the AI agent. The agent resolves them
# from config.yaml at runtime. No sed-based placeholder substitution needed.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/skills"
INSTALL_TARGET="$HOME/.hermes/skills/executive-briefing"
CONFIG="$SCRIPT_DIR/config.yaml"

if [ ! -f "$CONFIG" ]; then
    echo "❌ config.yaml not found: $CONFIG"
    exit 1
fi

# Parse config for display + directory creation only
OUTPUT_DIR=$(grep '^output_dir:' "$CONFIG" | sed 's/^output_dir: *"//;s/"$//' | envsubst | sed "s|^~|$HOME|")
HEALTH_DIR=$(grep '^health_data_dir:' "$CONFIG" | sed 's/^health_data_dir: *"//;s/"$//' | envsubst | sed "s|^~|$HOME|")
CHROME=$(grep '^chrome_path:' "$CONFIG" | sed 's/^chrome_path: *"//;s/"$//')

echo "📋 Configuration:"
echo "   output_dir:      $OUTPUT_DIR"
echo "   health_data_dir: $HEALTH_DIR"
echo "   chrome_path:     $CHROME"

# Install
if [ "$1" = "--dev" ]; then
    echo ""
    echo "🔧 Development mode (symlink → raw skills/)"
    if [ -L "$INSTALL_TARGET" ]; then
        rm "$INSTALL_TARGET"
    elif [ -d "$INSTALL_TARGET" ]; then
        echo "⚠️  $INSTALL_TARGET exists and is not a symlink. Backing up."
        mv "$INSTALL_TARGET" "${INSTALL_TARGET}.bak"
    fi
    ln -s "$SKILL_SRC" "$INSTALL_TARGET"
    echo "✅ symlink: $INSTALL_TARGET → $SKILL_SRC"
    echo "   Edit skills/ directly — changes are live immediately."
else
    echo ""
    echo "📦 Distribution mode (copy)"
    if [ -d "$INSTALL_TARGET" ]; then
        rm -rf "${INSTALL_TARGET}.bak" 2>/dev/null
        mv "$INSTALL_TARGET" "${INSTALL_TARGET}.bak"
    fi
    cp -r "$SKILL_SRC" "$INSTALL_TARGET"
    echo "✅ Installed: $INSTALL_TARGET"
fi

# Ensure output directories exist
mkdir -p "$OUTPUT_DIR"
mkdir -p "$HEALTH_DIR"

n_skills=$(find -L "$INSTALL_TARGET" -name 'SKILL.md' | wc -l | tr -d ' ')
echo ""
echo "📂 Output:       $OUTPUT_DIR"
echo "📊 Health data:  $HEALTH_DIR"
echo "📦 Skills:       $n_skills modules"
echo ""
echo "ℹ️  \${OUTPUT_DIR}, \${HEALTH_DATA_DIR}, \${CHROME_PATH} in SKILL.md"
echo "   are AI-agent notation — resolved from config.yaml at runtime."
