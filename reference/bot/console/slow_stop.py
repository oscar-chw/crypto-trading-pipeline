#!/usr/bin/env python3
"""
Toggle slow-stop mode: stop opening new entries, let positions manage exits.

This script modifies config.yaml directly, so changes are picked up by the trader
on the next config reload (within one cycle).

Usage:
  # enable slow-stop
  python bot/console/slow_stop.py --on

  # disable slow-stop
  python bot/console/slow_stop.py --off

  # check status
  python bot/console/slow_stop.py --status
"""

import argparse
import os
import re
import sys
import yaml


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--on', action='store_true')
    g.add_argument('--off', action='store_true')
    g.add_argument('--status', action='store_true')
    args = p.parse_args()

    # Find config.yaml path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, '..', 'config', 'config.yaml')
    config_path = os.path.abspath(config_path)
    
    if not os.path.exists(config_path):
        print(f"Error: config.yaml not found at {config_path}")
        return
    
    # Read current config for status check
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        return
    
    # Status check (read-only)
    if args.status:
        current = config.get('runtime', {}).get('slow_stop', False)
        print('slow-stop:', 'ON' if current else 'OFF', flush=True)
        return
    
    # Read file as text to preserve comments and formatting
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading config.yaml: {e}")
        return
    
    # Determine new value
    new_value = 'true' if args.on else 'false'
    
    # Find and replace the slow_stop line
    updated = False
    in_runtime_section = False
    new_lines = []
    
    for _i, line in enumerate(lines):
        # Check if we're in the runtime section
        if line.strip().startswith('runtime:'):
            in_runtime_section = True
            new_lines.append(line)
            continue
        
        # Check if we've left the runtime section (next top-level key)
        if in_runtime_section:
            # Check if this is a top-level key (starts at column 0, not a comment, not empty)
            stripped = line.strip()
            if stripped and not line.startswith(' ') and not line.startswith('\t') and not stripped.startswith('#'):
                in_runtime_section = False
        
        # If we're in runtime section, look for slow_stop line
        if in_runtime_section and 'slow_stop' in line:
            # Replace the value while preserving comments and formatting
            # Pattern: slow_stop: true/false  # comment
            # Match: slow_stop: <whitespace> true/false <optional whitespace> <optional comment>
            pattern = r'(slow_stop:\s*)(true|false)(\s*#.*)?'
            replacement = r'\1' + new_value + r'\3'
            new_line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
            new_lines.append(new_line)
            # Always mark as updated if we found and processed the slow_stop line
            updated = True
        else:
            new_lines.append(line)
    
    # If slow_stop line not found, add it after loop_interval_seconds
    if not updated:
        new_lines = []
        in_runtime_section = False
        for _i, line in enumerate(lines):
            new_lines.append(line)
            # Check if we're in the runtime section
            if line.strip().startswith('runtime:'):
                in_runtime_section = True
            # Check if we've left the runtime section
            elif in_runtime_section:
                stripped = line.strip()
                if stripped and not line.startswith(' ') and not line.startswith('\t') and not stripped.startswith('#'):
                    in_runtime_section = False
            # If we're in runtime section and find loop_interval_seconds, add slow_stop after it
            if in_runtime_section and 'loop_interval_seconds' in line:
                indent = len(line) - len(line.lstrip())
                new_lines.append(' ' * indent + f'slow_stop: {new_value}  # slow-stop mode: true = no new entries, but stop-loss and take-profit continue\n')
                updated = True
    
    # Write updated file
    if updated:
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f'slow-stop: {"ON" if args.on else "OFF"}', flush=True)
            print(f"Config updated: {config_path}", flush=True)
        except Exception as e:
            print(f"Error writing config.yaml: {e}", file=sys.stderr, flush=True)
            sys.exit(1)
    else:
        print("Warning: Could not find or update slow_stop in config.yaml", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

