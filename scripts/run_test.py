#!/usr/bin/env python3
"""
Automated test runner for Docker environment
Usage:
    python run_test.py <test_number|all> [--file <path>]

Examples:
    python run_test.py 1                    # Run test 1 with auto-generated file
    python run_test.py all                  # Run all tests
    python run_test.py 3 --file myfile.pdf  # Run test 3 with custom file
"""

import sys
import subprocess
import time
import hashlib
import json
from pathlib import Path
import threading
import queue
from test_utils import *
from test_utils import reset_network_conditions

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

    print("\n" + colored("=" * 70, YELLOW))
    print(colored(f" Starting Test {test_num}: {test_config['name']}", YELLOW))
    print(colored("=" * 70, YELLOW))
    print(colored(f"▶ Configuration  : {file_size}MB file, {timeout}s timeout", CYAN))
    
    client_conds = test_config.get("network_conditions", {}).get("client", {})
    client_params = [f"{k}={v}" for k, v in client_conds.items() if v]
    server_conds = test_config.get("network_conditions", {}).get("server", {})
    server_params = [f"{k}={v}" for k, v in server_conds.items() if v]
    
    print(colored(f"▶ Net Client     : {', '.join(client_params) if client_params else 'Normal'}", CYAN))
    print(colored(f"▶ Net Server     : {', '.join(server_params) if server_params else 'Normal'}", CYAN))
    print(colored("-" * 70, YELLOW))

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
    print(colored("\n" + "=" * 70, YELLOW))
    print(colored("Verifying file transfer...", YELLOW))
    print(colored("=" * 70, YELLOW))

    # Copy file from recived to temp for verification
    received_dir = Path(__file__).parent.parent / "recived"
    temp_dir = Path(__file__).parent.parent / "temp"
    temp_dir.mkdir(exist_ok=True)

    # List received files (copy from recived folder)
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
    print(colored("\n" + "=" * 70, YELLOW))
    if received_md5 and original_md5 == received_md5:
        print(colored(f"✓ Test {test_num} PASSED - File transferred successfully!", GREEN))
        print(colored(f"  Time taken: {elapsed_time:.2f}s", GREEN))
        print(colored("=" * 70, YELLOW))
        return True, elapsed_time
    else:
        if not received_md5:
            print(colored(f"✗ Test {test_num} FAILED - File not received", RED))
        else:
            print(colored(f"✗ Test {test_num} FAILED - File corrupted (MD5 mismatch)\n", RED))
            print(colored("Detailed Byte Analysis:", YELLOW))
            host_original_path = Path(__file__).parent.parent / "test" / filename
            try:
                with open(host_original_path, "rb") as f1, open(received_file_path, "rb") as f2:
                    d1 = f1.read()
                    d2 = f2.read()
                    print(f"  Expected Size: {len(d1)} bytes")
                    print(f"  Received Size: {len(d2)} bytes")
                    if len(d1) != len(d2):
                        diff = len(d2) - len(d1)
                        sign = "+" if diff > 0 else ""
                        print(colored(f"  Size differs by {sign}{diff} bytes!", RED))

                    for i in range(min(len(d1), len(d2))):
                        if d1[i] != d2[i]:
                            print(colored(f"  First mismatch at byte offset {i} (0x{i:04X})", RED))
                            print(f"    Expected: 0x{d1[i]:02X}")
                            print(f"    Received: 0x{d2[i]:02X}")
                            packet_approx = i / (10240 - 2)
                            print(f"    Approximate packet index: {packet_approx:.2f}")
                            break
            except Exception as e:
                print(f"  Could not run detailed analysis: {e}")

        print(colored("-" * 70, YELLOW))
        print(colored("Failed Test Configuration:", YELLOW))
        print(f"  Reproduce : python scripts/run_test.py {test_num}")
        print(f"  File size : {file_size}MB")
        print(f"  Time taken: {elapsed_time:.2f}s (Timeout: {timeout}s)")

        print(f"  Desc      : {test_config['name']}")
        for role in ["client", "server"]:
            conds = test_config["network_conditions"].get(role, {})
            params = [f"{k}={v}" for k, v in conds.items() if v]
            print(f"  {role.capitalize()}    : {', '.join(params) if params else 'Normal'}")

        print(colored("=" * 70, YELLOW))
        return False, elapsed_time

def print_congratulations():
    print("　　　　　　　　　　　　　　。・　　ﾟ　　★　。・　ﾟ　☆。 ・　ﾟ")
    print("　　　.へ￣＼　　　　　　｡･ﾟ・。・・。・　　。・・。 。・。 ・　ﾟ")
    print("　　　　＿| 二)＿　 ☆　   　　★・。ﾟ・　☆・　ﾟ　・　ﾟ。 ・　ﾟ")
    print("　　　　　(=ﾟωﾟ)っ／　　　　　　・。ﾟ　・　・。 ・　ﾟ　・　ﾟ。 ・　ﾟ")
    print("　   三》━/レθθ━　　 ☆ C o n g r a t u l a t i o n s ! ! ! ☆")
    print("　　　　　　　　 　　　　　　　☆　ﾟ　・　★ﾟ・　ﾟ　・　ﾟ　☆　ｷﾗ")
    print("\nSource: https://www.reddit.com/r/EmoticonHub/comments/1nvw9lu/congratulations_ascii_art/")

def print_test_summary_table(test_times, passed, failed, total_tests):
    """Print the final test summary as a formatted table"""
    table_width = 140
    print(f"\n{colored('='*table_width, YELLOW)}")
    print(colored(f"{'Test Summary':^{table_width}}", YELLOW))
    print(f"{colored('='*table_width, YELLOW)}")
    
    header = f"{'ID':^4} | {'Status':^6} | {'Time':^7} | {'Size':^6} | {'Client Net':^30} | {'Server Net':^30} | {'Description'}"
    print(header)
    print("-" * table_width)

    for test_num, success, elapsed in test_times:
        status_color = GREEN if success else RED
        status_text = "PASS" if success else "FAIL"
        
        test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), {})
        size = f"{test_config.get('file_size_mb', '-')}MB"
        desc = test_config.get('name', '-')
        
        client_conds = test_config.get("network_conditions", {}).get("client", {})
        client_params = [f"{k}={v}" for k, v in client_conds.items() if v]
        client_net = ", ".join(client_params) if client_params else "Normal"
        
        server_conds = test_config.get("network_conditions", {}).get("server", {})
        server_params = [f"{k}={v}" for k, v in server_conds.items() if v]
        server_net = ", ".join(server_params) if server_params else "Normal"
        
        status_formatted = colored(f"{status_text:^6}", status_color)
        
        row_prefix = f"{test_num:^4} | "
        row_suffix = f" | {elapsed:>6.2f}s | {size[:6]:>6} | {client_net[:30]:^30} | {server_net[:30]:^30} | {desc[:40]}"
        print(row_prefix + status_formatted + row_suffix)

    print(f"{colored('-'*table_width, YELLOW)}")
    
    summary_line = (colored(f"Passed: {passed}", GREEN) + " | " + 
                    colored(f"Failed: {failed}", RED) + f" | Total: {total_tests}")
    print(summary_line)
    print(f"{colored('='*table_width, YELLOW)}\n")

def run_all_tests():
    """Run all test cases from config.json"""
    passed = 0
    failed = 0
    test_times = []

    test_ids = [t["id"] for t in CONFIG["tests"]]
    total_tests = len(test_ids)

    for test_num in test_ids:
        success, elapsed = run_single_test(test_num)
        test_times.append((test_num, success, elapsed))

        if success:
            passed += 1
        else:
            failed += 1
        time.sleep(1)

    # Print summary
    print_test_summary_table(test_times, passed, failed, total_tests)

    if failed == 0:
        print_congratulations()
        print()

    return failed == 0

def main():
    print(f"\n{colored('='*70, YELLOW)}")
    print(colored("UDP Reliable File Transfer - Test Runner", YELLOW))
    print(f"{colored('='*70, YELLOW)}\n")

    if len(sys.argv) < 2:
        print("Usage: python run_test.py <test_number|all> [--file <path>]")
        print("\nExamples:")
        print("  python run_test.py 1              # Run test 1 with auto-generated file")
        print("  python run_test.py all            # Run all tests")
        print("  python run_test.py 3 --file myfile.bin  # Run test 3 with custom file")
        sys.exit(1)

    test_arg = sys.argv[1]
    custom_file = None

    # Check for --file argument
    if len(sys.argv) > 2 and sys.argv[2] == "--file":
        if len(sys.argv) < 4:
            print(colored("Error: --file requires a file path", RED))
            sys.exit(1)
        custom_file = sys.argv[3]

    # Start containers
    start_containers()

    # Run tests
    if test_arg.lower() == "all":
        if custom_file:
            print(colored("Warning: --file ignored when running all tests", YELLOW))
        success = run_all_tests()
    else:
        try:
            test_num = int(test_arg)
            test_ids = [t["id"] for t in CONFIG["tests"]]
            if test_num in test_ids:
                success, _ = run_single_test(test_num, custom_file)
            else:
                print(colored(f"Error: Test number must be one of {test_ids}", RED))
                sys.exit(1)
        except ValueError:
            print(colored("Error: Invalid test number", RED))
            sys.exit(1)

    print("\nTest run completed!")
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
