#!/usr/bin/env python3
import socket
import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from test_utils import *

def run_cleanup():
    """Main cleanup routine"""
    print_separator(YELLOW)
    print(colored(" Network and Process Cleanup", YELLOW))
    print_separator(YELLOW)

    # 1. Kill lingering processes
    print(colored("  [Cleanup] Killing lingering processes...", GRAY))
    cleanup_server()
    cleanup_client()

    # 2. Reset network conditions
    print(colored("  [Cleanup] Resetting network conditions...", GRAY))
    reset_network_conditions()

    # 3. Clear files
    print(colored("  [Cleanup] Clearing test files and local temp...", GRAY))
    cleanup_test_files()
    cleanup_local_temp()

    # 4. Drain packets (Inside container)
    drain_udp_packets("urft_server", CONFIG['server']['port'])
    drain_udp_packets("urft_client", CONFIG['server']['port'])

    print_separator(YELLOW)
    print(colored(" Cleanup completed successfully!", GREEN))
    print_separator(YELLOW + "\n")

if __name__ == "__main__":
    run_cleanup()
