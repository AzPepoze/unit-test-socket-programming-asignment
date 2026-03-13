# UDP Reliable File Transfer - Docker Testing Environment

Complete Docker testing environment with network simulation and **real-time code updates** (no rebuild needed!).

For just the sake just for testing so I just slap to the AI to create this project for test. So expect bugs you can open an issue if you find any. I will try to fix it as soon as possible.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Source Code Guidelines](#source-code-guidelines)
- [Quick Start](#quick-start)
     - [Run Docker Containers (First Time Only)](#run-docker-containers-first-time-only)
     - [Test with config.json scenarios](#test-with-configjson-scenarios)
     - [Test with custom files](#test-with-custom-files)
     - [Secret test case](#secret-test-case)
     - [Stop docker containers](#stop-docker-containers)
     - [Stop/Resume git tracking](#stopresume-git-tracking)
- [Usage](#usage)
     - [Running Tests](#running-tests)
     - [Manual Testing](#manual-testing)
     - [Custom Files](#custom-files)
- [Configuration](#configuration)
     - [Editing config.json](#editing-configjson)
     - [Test Scenarios](#test-scenarios)
- [Development](#development)
     - [Real-Time Updates](#real-time-updates)
     - [When to Rebuild](#when-to-rebuild)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- [**Docker** & **Docker Compose**](https://www.docker.com/)
- [**Python 3.7+**](https://www.python.org/downloads/)

## Source Code Guidelines

> [!IMPORTANT]
>
> - `src/urft_client.py`
>      - it's usage should be like
>           ```bash
>           python urft_client.py /path/to/file.bin <server_ip> <server_port>
>           ```
>      - path will pass like (e.g., `/path/to/file.bin`)
>           - it should automatically extract and send only the file name `(file.bin)` to the server, not the full path.
>      - terminates with `sys.exit(0)` after finished.
>           - ⚠️ This was unsure if it was required for the assignment, but for this test utility it is required for faster and correct time measurement
> - `src/urft_server.py`
>      - it's usage should be like
>           ```bash
>           python urft_server.py <server_ip> <server_port>
>           ```
>      - make sure to save received file with the same name as sent by the client (e.g., `file.bin`).
>      - terminates with `sys.exit(0)` after finished.
>           - ⚠️ This was unsure if it was required for the assignment, but for this test utility it is required for faster and correct time measurement

## Quick Start

### Run Docker Containers (First Time Only)

```bash
docker compose up -d
```

### Test with config.json scenarios

```bash
# 1. Run a test of scenario id 1 in config.json (starts containers automatically!)
python scripts/run_test.py 1

# Or run all tests
python scripts/run_test.py all

# Or run it 5 times to see MIN/MAX/AVG statistics
python scripts/run_test.py 1 5

# Or run all tests 3 times each
python scripts/run_test.py all 3

# 2. Edit your code in src/
# Changes are live - no rebuild needed!

# 3. Run tests again
python scripts/run_test.py 1
```

### Test with custom files

```bash
# Test with hi.txt with scenario id 1 in config.json
python scripts/run_test.py 1 --file test/hi.txt

# Test with keqing.png with scenario id 1 in config.json
python scripts/run_test.py 1 --file test/keqing.png
```

### Secret test case

```bash
python scripts/run_test.py 9
```

### Stop docker containers

```bash
docker compose down
```

### Stop/Resume git tracking 

`Stop` Git from tracking your local changes (useful for local configurations), run:
```bash
git update-index --skip-worktree src/urft_client.py src/urft_server.py
```
`Resume` tracking changes:
```bash
git update-index --no-skip-worktree src/urft_client.py src/urft_server.py
```

## Usage

### Running Tests

```bash
# Single test (1-8)
python scripts/run_test.py 3

# Single test multiple times (e.g., 5 times)
python scripts/run_test.py 3 5

# All tests
python scripts/run_test.py all

# All tests multiple times (e.g., 3 times each)
python scripts/run_test.py all 3
```

### Manual Testing

```bash
# Server (run explicitly in container)
docker exec -it urft_server python /app/src/urft_server.py 0.0.0.0 12345

# Client (in another terminal)
docker exec -it urft_client python /app/src/urft_client.py /app/test/testfile.bin 172.25.0.10 12345
```

### Custom Files

Test with your own files instead of generated random data:

```bash
# Test with PDF, image, video, etc.
python scripts/run_test.py 3 --file myfile.pdf
python scripts/run_test.py 1 5 --file document.docx  # Run 5 times
python scripts/run_test.py 5 3 --file video.mp4     # Run 3 times
```

## Configuration

### Editing config.json

Edit `config.json` to customize tests (changes apply immediately):

```json
{
	"tests": [
		{
			"id": 1,
			"file_size_mb": 1, // Change file size
			"timeout": 30, // Change timeout
			"network_conditions": {
				"client": {
					"delay": "5ms", // Add delay
					"loss": "2%", // Add packet loss
					"duplicate": null, // Add duplication
					"reorder": null // Add reordering
				}
			}
		}
	]
}
```

### Test Scenarios

Pre-configured test scenarios (edit in `config.json`):

| Test | File Size | RTT   | Client Conditions | Server Conditions | Timeout |
| ---- | --------- | ----- | ----------------- | ----------------- | ------- |
| 1    | 1 MB      | 10ms  | -                 | -                 | 30s     |
| 2    | 1 MB      | 10ms  | Dup: 2%           | -                 | 30s     |
| 3    | 1 MB      | 10ms  | Loss: 2%          | -                 | 30s     |
| 4    | 1 MB      | 10ms  | -                 | Dup: 5%           | 30s     |
| 5    | 1 MB      | 10ms  | -                 | Loss: 5%          | 30s     |
| 6    | 1 MB      | 250ms | -                 | -                 | 60s     |
| 7    | 1 MB      | 250ms | Reorder: 2%       | -                 | 90s     |
| 8    | 5 MB      | 100ms | Loss: 5%          | Loss: 2%          | 30s     |

## Development

### Real-Time Updates

**No rebuild needed!** Edit files on your host and changes apply instantly:

1. **Edit source code:**
     - `src/urft_client.py`
     - `src/urft_server.py`

2. **Edit configuration:**
     - `config.json`

3. **Test immediately:**

     ```bash
     python scripts/run_test.py 1  # Changes already applied!
     ```

**Volume Mounts:**

- `./src` → `/app/src` (live code updates)
- `./config.json` → `/app/config.json` (live config updates)
- `./test` & `./received` → File storage

### When to Rebuild

Only rebuild if you modify:

- `Dockerfile`
- `docker compose.yml`
- System dependencies

**Rebuild command:**

```bash
docker compose up -d --build
```

## Troubleshooting

If you encounter issues:

- **Containers won't start:** Run `docker compose up -d --build`
- **File transfer fails:** Make sure you start the server explicitly via `docker exec -it urft_server python /app/src/urft_server.py 0.0.0.0 12345` when testing manually.
- **Code changes not reflected:** Ensure the volume mounts (`./src:/app/src`) are working correctly.
