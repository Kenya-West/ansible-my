#!/bin/bash

# Default directory to the current working directory if not provided
TARGET_DIR="${1:-$(pwd)}"

# Function to remove empty directories
remove_empty_dirs() {
    local dir="$1"
    echo "Scanning directory: $dir"
    find "$dir" -type d -empty -print -delete
}

# Logging the start time
echo "---------------------------------"
echo "Cleanup started at $(date)"

# Call function to remove empty directories
remove_empty_dirs "$TARGET_DIR"

# Logging the completion time
echo "Cleanup completed at $(date)"
echo "---------------------------------"
