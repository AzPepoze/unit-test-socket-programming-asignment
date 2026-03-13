import subprocess
import time
import hashlib
import json
from pathlib import Path

# ANSI color codes
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[1;36m"
GRAY = "\033[0;90m"
NC = "\033[0m"  # No Color

# Load configuration
CONFIG_PATH = Path(__file__).parent.parent / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)


def colored(text, color):
    """Return colored text"""
    return f"{color}{text}{NC}"


def print_separator(color=YELLOW, char="=", length=70):
    """Print a horizontal separator line"""
    print(colored(char * length, color))


def read_stream(stream, queue_obj, prefix, color):
    """Read lines from stream in background thread"""
    try:
        for line in iter(stream.readline, ""):
            if line:
                queue_obj.put((prefix, color, line.rstrip()))
    except:
        pass
    finally:
        queue_obj.put(None)  # Signal EOF


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


def reset_network_conditions():
    """Tear down all tc rules on both containers (returns network to clean state)"""
    for container_name in ["urft_server", "urft_client"]:
        docker_exec(container_name, ["tc", "qdisc", "del", "dev", "eth0", "root"], capture=True)


def setup_network_conditions(test_num):
    """Apply network conditions from config"""
    print(colored("  [Setup] Setting up network conditions...", GRAY))

    # Find test config
    test_config = next((t for t in CONFIG["tests"] if t["id"] == test_num), None)
    if not test_config:
        print(colored(f"Error: Test {test_num} not found in config", RED))
        return False

    # Reset any leftover rules before applying new ones
    reset_network_conditions()

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
        success, stdout, stderr = docker_exec(container_name, cmd, capture=True)
        if stdout:
            for line in stdout.splitlines():
                print(colored(f"  [{container_name}] {line}", GRAY))
        if stderr:
            for line in stderr.splitlines():
                print(colored(f"  [{container_name} ERR] {line}", RED))
        if not success:
            print(colored(f"Error: Failed to setup network for {container_name}", RED))
            return False

    return True


def cleanup_test_files():
    """Clean up previous test files"""
    print(colored("  [Setup] Cleaning up previous test files...", GRAY))
    docker_exec("urft_client", ["sh", "-c", "rm -f /app/test/test_file_*mb_*.bin"], capture=True)
    docker_exec("urft_server", ["sh", "-c", "rm -rf /app/received/*"], capture=True)


def cleanup_local_temp():
    """Clean up local temporary folder"""
    import shutil
    temp_dir = Path(__file__).parent.parent / "temp"
    if temp_dir.exists():
        print(colored("  [Cleanup] Cleaning local temp folder...", GRAY))
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(exist_ok=True)


def create_test_file(size_mb):
    """Create test file in container with a random suffix"""
    import random
    import string
    random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    filename = f"test_file_{size_mb}mb_{random_suffix}.bin"
    print(colored(f"  [Setup] Creating {size_mb}MB test file: {filename}...", GRAY))

    docker_exec("urft_client", ["mkdir", "-p", "/app/test"], capture=True)
    python_cmd = [
        "python",
        "-c",
        f"import os; " f"filepath = '/app/test/{filename}'; " f"f = open(filepath, 'wb'); " f"[f.write(os.urandom(1024*1024)) for _ in range({size_mb})]; " f"f.close(); " f"print(filepath)",
    ]

    success, stdout, _ = docker_exec("urft_client", python_cmd, capture=True)
    if success:
        print(colored(f"  [Setup] Created: {stdout}", GRAY))
    return filename if success else None


def use_custom_file(host_filepath):
    """Copy custom file from host to container /app/tmp/"""
    filepath = Path(host_filepath)

    if not filepath.exists():
        print(colored(f"Error: File not found: {filepath}", RED))
        return None

    filename = filepath.name
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    print(colored(f"  [Setup] Using custom file: {filename} ({file_size_mb:.2f} MB)", GRAY))

    # Ensure /app/test exists in both containers
    docker_exec("urft_client", ["mkdir", "-p", "/app/test"], capture=True)

    # Copy file to client container
    container_path = f"urft_client:/app/test/{filename}"
    try:
        subprocess.run(["docker", "cp", str(filepath), container_path], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(colored(f"Error copying file to urft_client: {e}", RED))
        return None

    print(colored(f"  [Setup] Copied to: /app/test/{filename}", GRAY))
    return filename


def calculate_md5(container, filepath):
    """Calculate MD5 hash of a file in container"""
    cmd = f"md5sum {filepath}"
    success, output, _ = docker_exec(container, cmd, capture=True)
    if success and output:
        # md5sum output format: "hash  filename"
        return output.split()[0]
    return None


def calculate_md5_local(filepath):
    """Calculate MD5 hash of a file on host filesystem"""
    try:
        with open(filepath, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except:
        return None


def drain_udp_packets(container_name, port):
    """Drain UDP packets from a specific port in a container"""
    drain_python = f"""
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('0.0.0.0', {port}))
    s.settimeout(0.2)
    count = 0
    while True:
        s.recvfrom(65535)
        count += 1
except socket.timeout:
    print(f'Drained {{count}} packets')
except Exception as e:
    print(f'Error: {{e}}')
finally:
    s.close()
"""
    print(colored(f"  [Cleanup] Draining UDP packets on port {port} in {container_name}...", GRAY))
    return docker_exec(container_name, ["python", "-c", drain_python], capture=True)


def compare_files(expected_path, received_path):
    """Perform detailed byte analysis between two files"""
    try:
        with open(expected_path, "rb") as f1, open(received_path, "rb") as f2:
            data_expected = f1.read()
            data_received = f2.read()
            print(f"  Expected Size: {len(data_expected)} bytes")
            print(f"  Received Size: {len(data_received)} bytes")
            if len(data_expected) != len(data_received):
                size_difference = len(data_received) - len(data_expected)
                sign = "+" if size_difference > 0 else ""
                print(colored(f"  Size differs by {sign}{size_difference} bytes!", RED))

            for i in range(min(len(data_expected), len(data_received))):
                if data_expected[i] != data_received[i]:
                    print(colored(f"  First mismatch at byte offset {i} (0x{i:04X})", RED))
                    print(f"    Expected: 0x{data_expected[i]:02X}")
                    print(f"    Received: 0x{data_received[i]:02X}")
                    packet_index_approx = i / (10240 - 2)
                    print(f"    Approximate packet index: {packet_index_approx:.2f}")
                    break
    except Exception as e:
        print(f"  Could not run detailed analysis: {e}")


def print_congratulations():
    """Print ASCII art congratulations message"""
    print("　　　　　　　　　　　　　　。・　　ﾟ　　★　。・　ﾟ　☆。 ・　ﾟ")
    print("　　　.へ￣＼　　　　　　｡･ﾟ・。・・。・　　。・・。 。・。 ・　ﾟ")
    print("　　　　＿| 二)＿　 ☆　   　　★・。ﾟ・　☆・　ﾟ　・　ﾟ。 ・　ﾟ")
    print("　　　　　(=ﾟωﾟ)っ／　　　　　　・。ﾟ　・　・。 ・　ﾟ　・　ﾟ。 ・　ﾟ")
    print("　   三》━/レθθ━　　 ☆ C o n g r a t u l a t i o n s ! ! ! ☆")
    print("　　　　　　　　 　　　　　　　☆　ﾟ　・　★ﾟ・　ﾟ　・　ﾟ　☆　ｷﾗ")
    print("\nSource: https://www.reddit.com/r/EmoticonHub/comments/1nvw9lu/congratulations_ascii_art/")


def cleanup_server():
    """Kill any lingering server processes"""
    python_cmd = """
import os, signal
for pid in os.listdir('/proc'):
    if pid.isdigit() and int(pid) != 1 and int(pid) != os.getpid():
        try:
            with open(f'/proc/{pid}/cmdline', 'r') as f:
                if 'urft_server.py' in f.read():
                    os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass
"""
    docker_exec("urft_server", ["python", "-c", python_cmd], capture=False)


def cleanup_client():
    """Kill any lingering client processes"""
    python_cmd = """
import os, signal
for pid in os.listdir('/proc'):
    if pid.isdigit() and int(pid) != 1 and int(pid) != os.getpid():
        try:
            with open(f'/proc/{pid}/cmdline', 'r') as f:
                if 'urft_client.py' in f.read():
                    os.kill(int(pid), signal.SIGKILL)
        except Exception:
            pass
"""
    docker_exec("urft_client", ["python", "-c", python_cmd], capture=False)


def start_containers():
    """Start Docker containers"""
    print(colored("[Docker] Starting Docker containers...", CYAN))
    # Run from project root, docker-compose.yml is in root
    script_dir = Path(__file__).parent.parent  # Go to project root
    compose_file = script_dir / "docker-compose.yml"
    run_command(f"docker compose -f {compose_file} up -d", capture=True)
    print(colored("[Docker] Waiting for containers to be ready...", CYAN))
    time.sleep(1)
