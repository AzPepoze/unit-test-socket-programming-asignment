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
import os
import shutil
import hashlib
import json
from pathlib import Path

# ANSI color codes
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
NC = "\033[0m"  # No Color

# Load configuration
CONFIG_PATH = Path(__file__).parent.parent / "config.json"
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)


def colored(text, color):
    """Return colored text"""
    return f"{color}{text}{NC}"


def run_command(cmd, capture=True, check=False):
    """Run a shell command"""
    try:
        if capture:
            result = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, check=check)
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        else:
            result = subprocess.run(cmd, shell=isinstance(cmd, str), check=check)
            return result.returncode == 0, "", ""
    except subprocess.CalledProcessError as e:
        return False, "", str(e)
    except Exception as e:
        return False, "", str(e)


def docker_exec(container, command, capture=True):
    """Execute command in Docker container"""
    cmd = ["docker", "exec", container] + (command if isinstance(command, list) else command.split())
    return run_command(cmd, capture=capture)


def setup_network_conditions(test_num):
    """Apply network conditions from config"""
    print("Setting up network conditions...")

    # Find test config
    test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), None)
    if not test_config:
        print(colored(f"Error: Test {test_num} not found in config", RED))
        return False

    print(f"Test: {test_config['name']}")

    # Apply network conditions to each container
    for container_name in ["urft_server", "urft_client"]:
        container_key = "server" if container_name == "urft_server" else "client"
        conditions = test_config["network_conditions"][container_key]

        delay = conditions.get("delay", "null")
        loss = conditions.get("loss", "null")
        duplicate = conditions.get("duplicate", "null")
        reorder = conditions.get("reorder", "null")

        # Convert None to 'null'
        delay = delay if delay else "null"
        loss = loss if loss else "null"
        duplicate = duplicate if duplicate else "null"
        reorder = reorder if reorder else "null"

        cmd = f"sh /app/scripts/network_setup.sh {delay} {loss} {duplicate} {reorder}"
        success, _, _ = docker_exec(container_name, cmd, capture=False)
        if not success:
            print(f"Warning: Failed to setup network for {container_name}")

    return True


def cleanup_test_files():
    """Clean up previous test files"""
    print("Cleaning up previous test files...")
    docker_exec("urft_test", ["sh", "-c", "rm -rf /app/recived/*.bin"], capture=False)
    docker_exec("urft_test", ["sh", "-c", "rm -rf /app/test/*.bin"], capture=False)


def create_test_file(size_mb):
    """Create test file in container"""
    filename = f"test_file_{size_mb}mb.bin"
    print(f"Creating {size_mb}MB test file...")

    python_cmd = [
        "python",
        "-c",
        f"import os; " f"filepath = '/app/test/{filename}'; " f"f = open(filepath, 'wb'); " f"[f.write(os.urandom(1024*1024)) for _ in range({size_mb})]; " f"f.close(); " f"print(filepath)",
    ]

    success, stdout, _ = docker_exec("urft_test", python_cmd, capture=True)
    if success:
        print(f"Created: {stdout}")
    return filename if success else None


def use_custom_file(host_filepath):
    """Copy custom file from host to container"""
    filepath = Path(host_filepath)

    if not filepath.exists():
        print(colored(f"Error: File not found: {filepath}", RED))
        return None

    filename = filepath.name
    print(f"Using custom file: {filename} ({filepath.stat().st_size / (1024*1024):.2f} MB)")

    script_dir = Path(__file__).parent.parent
    test_dir = script_dir / "test"
    test_dir.mkdir(exist_ok=True)

    dest = test_dir / filename
    shutil.copy2(filepath, dest)
    print(f"Copied to: {dest}")

    return filename


def calculate_md5(container, filepath):
    """Calculate MD5 hash of a file in container"""
    cmd = f"md5sum {filepath}"
    success, output, _ = docker_exec(container, cmd, capture=True)
    if success and output:
        # md5sum output format: "hash  filename"
        return output.split()[0]
    return None


def restart_server():
    """Restart the server process"""
    print("Restarting server...")
    # Note: Server should be running via docker-compose command
    # No need to restart for each test
    time.sleep(1)


def run_single_test(test_num, custom_file=None):
    """Run a single test - Get test configuration from config.json"""
    test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), None)
    if not test_config:
        print(colored(f"Error: Test {test_num} not found in config.json", RED))
        return False

    file_size = test_config["file_size_mb"]
    timeout = test_config["timeout"]
    points = test_config["points"]

    print(f"Configuration: {file_size}MB file, {timeout}s timeout, {points} points")
    print(f"Description: {test_config['name']}")

    # Setup network conditions
    if not setup_network_conditions(test_num):
        return False

    # Clean up previous test
    cleanup_test_files()

    # Create or use test file
    if custom_file:
        filename = use_custom_file(custom_file)
        if not filename:
            print(colored("✗ Failed to use custom file", RED))
            return False
    else:
        filename = create_test_file(file_size)
        if not filename:
            print(colored("✗ Failed to create test file", RED))
            return False

    # Restart server
    restart_server()

    # Calculate original MD5
    original_path = f"/app/test/{filename}"
    original_md5 = calculate_md5("urft_test", original_path)
    print(f"Original MD5:  {original_md5}")

    # Run client transfer
    print("\n" + colored("=" * 70, YELLOW))
    print(colored("Starting file transfer...", YELLOW))
    print(colored("=" * 70, YELLOW))

    client_cmd = ["python", "/app/src/urft_client.py", original_path, CONFIG["docker"]["server_ip"], str(CONFIG["server"]["port"])]

    # Start client with output visible
    try:
        print(colored("\n[CLIENT OUTPUT]", GREEN))
        print("-" * 70)

        proc = subprocess.Popen(["docker", "exec", "urft_client"] + client_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        # Read output in real-time
        print(f"Waiting for transfer (timeout: {timeout}s)...")
        start_time = time.time()

        try:
            while True:
                # Check if process finished
                if proc.poll() is not None:
                    break

                # Check timeout
                if time.time() - start_time > timeout:
                    proc.kill()
                    print(colored("\n⚠ Transfer timed out", YELLOW))
                    break

                # Read output line by line
                line = proc.stdout.readline()
                if line:
                    print(line.rstrip())
                else:
                    time.sleep(0.1)

        except KeyboardInterrupt:
            proc.kill()
            raise

        # Get any remaining output
        remaining = proc.stdout.read()
        if remaining:
            print(remaining.rstrip())

        print("-" * 70)

        # Show server logs
        print(colored("\n[SERVER OUTPUT]", GREEN))
        print("-" * 70)
        success, server_logs, _ = run_command(["docker", "logs", "--tail", "50", "urft_server"], capture=True)
        if success and server_logs:
            print(server_logs)
        print("-" * 70)

    except Exception as e:
        print(colored(f"Error running client: {e}", RED))
        return False

    # Give a bit more time for cleanup
    time.sleep(2)

    # Verify file transfer
    print(colored("\n" + "=" * 70, YELLOW))
    print(colored("Verifying file transfer...", YELLOW))
    print(colored("=" * 70, YELLOW))

    # List received files
    success, files, _ = docker_exec("urft_server", "ls -lh /app/recived/")
    if success and files:
        print("\nReceived files:")
        print(files)

    # Calculate received MD5
    received_path = f"/app/recived/{filename}"
    received_md5 = calculate_md5("urft_server", received_path)

    print(f"\nOriginal MD5: {original_md5}")
    print(f"Received MD5: {received_md5 if received_md5 else 'FILE NOT FOUND'}")

    # Check if test passed
    print(colored("\n" + "=" * 70, YELLOW))
    if received_md5 and original_md5 == received_md5:
        print(colored(f"✓ Test {test_num} PASSED - File transferred successfully!", GREEN))
        print(colored("=" * 70, YELLOW))
        return True
    else:
        if not received_md5:
            print(colored(f"✗ Test {test_num} FAILED - File not received", RED))
        else:
            print(colored(f"✗ Test {test_num} FAILED - File corrupted (MD5 mismatch)", RED))
        print(colored("=" * 70, YELLOW))
        return False


def start_containers():
    """Start Docker containers"""
    print("Starting Docker containers...")
    # Run from project root, docker-compose.yml is in root
    script_dir = Path(__file__).parent.parent  # Go to project root
    compose_file = script_dir / "docker-compose.yml"
    run_command(f"docker-compose -f {compose_file} up -d", capture=False)
    print("Waiting for containers to be ready...")
    time.sleep(3)


def run_all_tests():
    """Run all 8 test cases"""
    passed = 0
    failed = 0

    for test_num in range(1, 9):
        if run_single_test(test_num):
            passed += 1
        else:
            failed += 1
        time.sleep(2)

    # Print summary
    print(f"\n{colored('='*70, YELLOW)}")
    print(colored("Test Summary", YELLOW))
    print(f"{colored('='*70, YELLOW)}")
    print(colored(f"Passed: {passed}", GREEN))
    print(colored(f"Failed: {failed}", RED))
    print(f"Total:  8")
    print(f"{colored('='*70, YELLOW)}\n")

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
                success = run_single_test(test_num, custom_file)
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
