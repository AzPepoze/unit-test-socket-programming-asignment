import sys
import subprocess
import time
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
    docker_exec("urft_client", ["sh", "-c", "rm -f /app/test/test_file_*mb.bin"], capture=False)
    docker_exec("urft_server", ["sh", "-c", "rm -rf /app/recived/*"], capture=False)

def create_test_file(size_mb):
    """Create test file in container"""
    filename = f"test_file_{size_mb}mb.bin"
    print(f"Creating {size_mb}MB test file...")

    docker_exec("urft_client", ["mkdir", "-p", "/app/test"], capture=False)
    python_cmd = [
        "python",
        "-c",
        f"import os; " f"filepath = '/app/test/{filename}'; " f"f = open(filepath, 'wb'); " f"[f.write(os.urandom(1024*1024)) for _ in range({size_mb})]; " f"f.close(); " f"print(filepath)",
    ]

    success, stdout, _ = docker_exec("urft_client", python_cmd, capture=True)
    if success:
        print(f"Created: {stdout}")
    return filename if success else None

def use_custom_file(host_filepath):
    """Copy custom file from host to container /app/tmp/"""
    filepath = Path(host_filepath)

    if not filepath.exists():
        print(colored(f"Error: File not found: {filepath}", RED))
        return None

    filename = filepath.name
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"Using custom file: {filename} ({file_size_mb:.2f} MB)")

    # Ensure /app/test exists in both containers
    docker_exec("urft_client", ["mkdir", "-p", "/app/test"], capture=False)

    # Copy file to client container
    container_path = f"urft_client:/app/test/{filename}"
    try:
        subprocess.run(["docker", "cp", str(filepath), container_path], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(colored(f"Error copying file to urft_client: {e}", RED))
        return None

    print(f"Copied to: /app/test/{filename}")
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
    print("Starting Docker containers...")
    # Run from project root, docker-compose.yml is in root
    script_dir = Path(__file__).parent.parent  # Go to project root
    compose_file = script_dir / "docker-compose.yml"
    run_command(f"docker compose -f {compose_file} up -d", capture=False)
    print("Waiting for containers to be ready...")
    time.sleep(1)
