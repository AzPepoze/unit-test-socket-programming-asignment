#!/usr/bin/env python3
"""
Automated test runner for Docker environment
Usage:
    python run_test.py <test_number|all> [times] [--file <path>]

Examples:
    python run_test.py 1                    # Run test 1 once
    python run_test.py 1 5                  # Run test 1 five times
    python run_test.py all                  # Run all tests once
    python run_test.py all 5                # Run all tests five times
    python run_test.py 3 5 --file myfile.pdf  # Run test 3 five times with custom file
"""
import sys
import subprocess
import time
import threading
import queue
from pathlib import Path
sys.path.append(str(Path(__file__).parent))

from test_utils import *
from test_utils import reset_network_conditions
from cleanup import run_cleanup


def run_single_test(test_num, custom_file=None):
    """Run a single test - Get test configuration from config.json"""
    test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), None)
    if not test_config:
        print(colored(f"Error: Test {test_num} not found in config.json", RED))
        return False, 0.0

    file_size = test_config["file_size_mb"]
    timeout = test_config["timeout"]

    # Setup network conditions
    if not setup_network_conditions(test_num):
        return False, 0.0

    # Clean up previous test
    cleanup_test_files()

    # Create or use test file
    if custom_file:
        filename = use_custom_file(custom_file)
        if not filename:
            print(colored("✗ Failed to use custom file", RED))
            return False, 0.0
    else:
        filename = create_test_file(file_size)
        if not filename:
            print(colored("✗ Failed to create test file", RED))
            return False, 0.0

    # Cleanup server and client
    cleanup_server()
    cleanup_client()

    # Calculate original MD5
    original_path = f"/app/test/{filename}"
    original_md5 = calculate_md5("urft_client", original_path)
    print(colored(f"  [Setup] Original MD5   : {original_md5}", GRAY))

    print_separator(YELLOW)
    print(colored(f" Starting Test {test_num}: {test_config['name']}", YELLOW))
    print_separator(YELLOW)
    print(colored(f"▶ Configuration  : {file_size}MB file, {timeout}s timeout", CYAN))

    client_conds = test_config.get("network_conditions", {}).get("client", {})
    client_params = [f"{k}={v}" for k, v in client_conds.items() if v]
    server_conds = test_config.get("network_conditions", {}).get("server", {})
    server_params = [f"{k}={v}" for k, v in server_conds.items() if v]

    print(colored(f"▶ Net Client     : {', '.join(client_params) if client_params else 'Normal'}", CYAN))
    print(colored(f"▶ Net Server     : {', '.join(server_params) if server_params else 'Normal'}", CYAN))
    print_separator(YELLOW, char="-")

    # Run client transfer

    server_cmd = ["python", "-u", "/app/src/urft_server.py", "0.0.0.0", str(CONFIG["server"]["port"])]
    client_cmd = ["python", "-u", "/app/src/urft_client.py", original_path, CONFIG["docker"]["server_ip"], str(CONFIG["server"]["port"])]

    # Start client with output visible
    try:
        # Start server process in background
        server_proc = subprocess.Popen(["docker", "exec", "urft_server"] + server_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        time.sleep(1)  # Wait for server to bind

        # Start client process
        client_proc = subprocess.Popen(["docker", "exec", "urft_client"] + client_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        # Create queue for output and start reader threads
        output_queue = queue.Queue()
        server_thread = threading.Thread(target=read_stream, args=(server_proc.stdout, output_queue, "[SERVER] ", GREEN), daemon=True)
        client_thread = threading.Thread(target=read_stream, args=(client_proc.stdout, output_queue, "[CLIENT] ", YELLOW), daemon=True)

        server_thread.start()
        client_thread.start()

        # Read both outputs in real-time
        start_time = time.time()
        client_done = False
        server_done = False
        eof_count = 0
        elapsed_time = 0

        try:
            while True:
                # Check timeout
                current_time = time.time()
                elapsed_time = current_time - start_time
                if elapsed_time > timeout:
                    client_proc.kill()
                    print(colored("\n⚠ Transfer timed out", YELLOW))
                    break

                # Check if client finished
                if client_proc.poll() is not None and not client_done:
                    client_done = True

                # Read available output (non-blocking)
                try:
                    item = output_queue.get(timeout=0.1)
                    if item is None:
                        eof_count += 1
                        if eof_count >= 2:  # Both streams closed
                            break
                    else:
                        prefix, color, line = item
                        print(colored(prefix, color) + line)
                        if "File transfer completed." in line and prefix == "[SERVER] ":
                            server_done = True
                except queue.Empty:
                    pass

                if client_done and server_done:
                    break

        except KeyboardInterrupt:
            client_proc.kill()
            server_proc.kill()
            cleanup_server()
            raise

        # Stop server process
        server_proc.kill()
        server_proc.wait()
        cleanup_server()
        cleanup_client()
        reset_network_conditions()

        print(colored("-" * 70, GRAY))

    except Exception as e:
        print(colored(f"Error running client: {e}", RED))
        cleanup_server()
        cleanup_client()
        reset_network_conditions()
        return False, 0.0

    # Verify file transfer
    print_separator(YELLOW)
    print(colored("Verifying file transfer...", YELLOW))
    print_separator(YELLOW)

    # Copy file from received to temp for verification
    received_dir = Path(__file__).parent.parent / "received"
    temp_dir = Path(__file__).parent.parent / "temp"
    temp_dir.mkdir(exist_ok=True)

    # List received files (copy from received folder)
    if received_dir.exists():
        files = list(received_dir.glob("*"))
        files = [f for f in files if f.is_file()]
        if files:
            print("\nReceived files:")
            for f in files:
                print(f"  {f.name}")
                # Copy to temp folder
                import shutil

                shutil.copy(f, temp_dir / f.name)

    # Calculate received MD5 (from temp folder)
    received_file_path = temp_dir / filename
    if received_file_path.exists():
        received_md5 = calculate_md5_local(received_file_path)
    else:
        received_md5 = None

    print(f"\nOriginal MD5: {original_md5}")
    print(f"Received MD5: {received_md5 if received_md5 else 'FILE NOT FOUND'}")

    # Check if test passed
    print_separator(YELLOW)
    if received_md5 and original_md5 == received_md5:
        print(colored(f"✓ Test {test_num} PASSED - File transferred successfully!", GREEN))
        print(colored(f"  Time taken: {elapsed_time:.2f}s", GREEN))
        print_separator(YELLOW)
        return True, elapsed_time
    else:
        if not received_md5:
            print(colored(f"✗ Test {test_num} FAILED - File not received", RED))
        else:
            print(colored(f"✗ Test {test_num} FAILED - File corrupted (MD5 mismatch)\n", RED))
            print(colored("Detailed Byte Analysis:", YELLOW))
            host_original_path = Path(__file__).parent.parent / "test" / filename
            compare_files(host_original_path, received_file_path)

        print_separator(YELLOW, char="-")
        print(colored("Failed Test Configuration:", YELLOW))
        print(f"  Reproduce : python scripts/run_test.py {test_num}")
        print(f"  File size : {file_size}MB")
        print(f"  Time taken: {elapsed_time:.2f}s (Timeout: {timeout}s)")

        print(f"  Desc      : {test_config['name']}")
        for role in ["client", "server"]:
            conds = test_config["network_conditions"].get(role, {})
            params = [f"{k}={v}" for k, v in conds.items() if v]
            print(f"  {role.capitalize()}    : {', '.join(params) if params else 'Normal'}")

        print_separator(YELLOW)
        return False, elapsed_time


def run_test_with_iterations(test_id, times, custom_file=None):
    """Run a specific test for a number of iterations"""
    runs = []
    for iteration in range(times):
        if times > 1:
            print(colored(f"\n[Iteration {iteration+1}/{times}]", CYAN))
        success, elapsed = run_single_test(test_id, custom_file)
        runs.append((success, elapsed))
        time.sleep(1)
    return runs


def print_test_summary_table(all_results):
    """Print the final test summary as a formatted table with vertical time statistics"""
    table_width = 135
    print_separator(YELLOW, length=table_width)
    print(colored(f"{'Test Summary':^{table_width}}", YELLOW))
    print_separator(YELLOW, length=table_width)

    header = f"{'ID':^4} | {'Status':^10} | {'Time':^10} | {'Size':^8} | {'Client Net':^25} | {'Server Net':^25} | {'Description'}"
    print(header)
    print("-" * table_width)

    total_passed = 0
    total_runs = 0

    for i, (test_num, runs) in enumerate(all_results.items()):
        successes = [r[0] for r in runs]
        times = [r[1] for r in runs if r[0]]  # Only consider times for successful runs

        passed_count = sum(1 for s in successes if s)
        run_count = len(successes)
        total_passed += passed_count
        total_runs += run_count

        if run_count == 1:
            status_text = "PASS" if passed_count == run_count else "FAILED"
        else:
            status_text = f"{passed_count}/{run_count} PASS" if passed_count == run_count else f"{passed_count}/{run_count} FAIL"

        status_color = GREEN if passed_count == run_count else (YELLOW if passed_count > 0 else RED)
        status_formatted = colored(f"{status_text:^10}", status_color)

        test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), {})
        size = f"{test_config.get('file_size_mb', '-')}MB"
        desc = test_config.get("name", "-")

        client_conds = test_config.get("network_conditions", {}).get("client", {})
        client_params = [f"{k}={v}" for k, v in client_conds.items() if v]
        client_net = ", ".join(client_params) if client_params else "Normal"

        server_conds = test_config.get("network_conditions", {}).get("server", {})
        server_params = [f"{k}={v}" for k, v in server_conds.items() if v]
        server_net = ", ".join(server_params) if server_params else "Normal"

        if run_count == 1:
            # Single run format: Show as a single row
            time_str = f"{times[0]:.2f}s" if times else "N/A"
            print(f"{test_num:^4} | {status_formatted} | {time_str:>10} | {size:^8} | {client_net[:25]:^25} | {server_net[:25]:^25} | {desc[:37]}")
        else:
            # Multiple runs format: Vertical time statistics (3 rows)
            if times:
                min_t = f"MIN: {min(times):.2f}s"
                max_t = f"MAX: {max(times):.2f}s"
                avg_t = f"AVG: {sum(times)/len(times):.2f}s"
            else:
                min_t = "MIN: N/A"
                max_t = "MAX: N/A"
                avg_t = "AVG: N/A"

            # Row 1: MIN
            print(f"{' ':^4} | {' ':^10} | {min_t:<10} | {' ':^8} | {' ':^25} | {' ':^25} | {' ':^37}")
            # Row 2: ID, Status, AVG, Size, Net conditions, Description
            print(f"{test_num:^4} | {status_formatted} | {avg_t:<10} | {size:^8} | {client_net[:25]:^25} | {server_net[:25]:^25} | {desc[:37]}")
            # Row 3: MAX
            print(f"{' ':^4} | {' ':^10} | {max_t:<10} | {' ':^8} | {' ':^25} | {' ':^25} | {' ':^37}")

        # Only print separator if not the last item and there are multiple runs (to separate different tests)
        if i < len(all_results) - 1 and run_count > 1:
            print("-" * table_width)

    # Use double line separator before summary
    print_separator(YELLOW, length=table_width)
    summary_line = colored(f"Total Passed: {total_passed}/{total_runs}", GREEN if total_passed == total_runs else YELLOW)
    print(summary_line)
    print_separator(YELLOW, length=table_width)
    print()


def run_all_tests(times=1):
    """Run all test cases from config.json"""
    all_results = {}
    test_ids = [t["id"] for t in CONFIG["tests"] if t.get("required", True)]

    for test_num in test_ids:
        runs = run_test_with_iterations(test_num, times)
        all_results[test_num] = runs

    # Print summary
    print_test_summary_table(all_results)

    all_passed = all(all(r[0] for r in runs) for runs in all_results.values())
    if all_passed:
        print_congratulations()
        print()

    return all_passed


def main():
    print_separator(YELLOW)
    print(colored("UDP Reliable File Transfer - Test Runner", YELLOW))
    print_separator(YELLOW)
    print()

    if len(sys.argv) < 2:
        print("Usage: python run_test.py <test_number|all> [times] [--file <path>]")
        print("\nExamples:")
        print("  python run_test.py 1              # Run test 1 once")
        print("  python run_test.py 1 5            # Run test 1 five times")
        print("  python run_test.py all            # Run all tests once")
        print("  python run_test.py all 5          # Run all tests five times")
        print("  python run_test.py 3 5 --file myfile.bin  # Run test 3 five times with custom file")
        sys.exit(1)

    test_arg = sys.argv[1]
    times = 1
    custom_file = None

    # Simple argument parsing
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--file":
            if i + 1 < len(args):
                custom_file = args[i + 1]
                i += 2
            else:
                print(colored("Error: --file requires a file path", RED))
                sys.exit(1)
        else:
            try:
                times = int(args[i])
                i += 1
            except ValueError:
                print(colored(f"Error: Invalid argument '{args[i]}'", RED))
                sys.exit(1)

    # Run cleanup first
    run_cleanup()

    # Start containers
    start_containers()

    # Run tests
    if test_arg.lower() == "all":
        if custom_file:
            print(colored("Warning: --file ignored when running all tests", YELLOW))
        success = run_all_tests(times)
    else:
        try:
            test_id = int(test_arg)
            test_ids = [t["id"] for t in CONFIG["tests"]]
            if test_id in test_ids:
                runs = run_test_with_iterations(test_id, times, custom_file)
                print_test_summary_table({test_id: runs})
                success = all(r[0] for r in runs)
            else:
                print(colored(f"Error: Test number must be one of {test_ids}", RED))
                sys.exit(1)
        except ValueError:
            print(colored("Error: Invalid test number", RED))
            sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
