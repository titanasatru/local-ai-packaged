#!/usr/bin/env python3
"""
start_services.py

This script starts the Supabase stack first, waits for it to initialize, and then starts
the local AI stack. Both stacks use the same Docker Compose project name ("localai").
"""

import os
import subprocess
import shutil
import time
import argparse
import platform
import sys

def run_command(cmd, cwd=None):
    """Run a shell command and print it."""
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def clone_supabase_repo():
    """Clone the Supabase repository using sparse checkout if not already present."""
    if not os.path.exists("supabase"):
        print("Cloning the Supabase repository...")
        run_command([
            "git", "clone", "--filter=blob:none", "--no-checkout",
            "https://github.com/supabase/supabase.git"
        ])
        os.chdir("supabase")
        run_command(["git", "sparse-checkout", "init", "--cone"])
        run_command(["git", "sparse-checkout", "set", "docker"])
        run_command(["git", "checkout", "master"])
        os.chdir("..")
    else:
        print("Supabase repository already exists, updating...")
        os.chdir("supabase")
        run_command(["git", "pull"])
        os.chdir("..")

def prepare_supabase_env():
    """Copy .env to .env in supabase/docker."""
    env_path = os.path.join("supabase", "docker", ".env")
    env_example_path = os.path.join(".env")
    print("Copying .env in root to .env in supabase/docker...")
    shutil.copyfile(env_example_path, env_path)

def create_docker_network():
    """Create localai-net Docker network if it doesn't exist."""
    print("Checking for localai-net Docker network...")
    result = subprocess.run(["docker", "network", "ls", "--filter", "name=localai-net", "--format", "{{.Name}}"],
                           capture_output=True, text=True)
    if "localai-net" not in result.stdout:
        print("Creating localai-net Docker network...")
        run_command(["docker", "network", "create", "localai-net"])
    else:
        print("localai-net already exists.")

def stop_existing_containers():
    """Stop and remove existing containers for our unified project ('localai')."""
    print("Stopping and removing existing containers for the unified project 'localai'...")
    run_command([
        "docker", "compose",
        "-p", "localai",
        "-f", "docker-compose.yml",
        "-f", "supabase/docker/docker-compose.yml",
        "down"
    ])

def start_supabase():
    """Start the Supabase services."""
    print("Starting Supabase services...")
    run_command([
        "docker", "compose", "-p", "localai", "-f", "supabase/docker/docker-compose.yml", "up", "-d"
    ])

def start_local_ai(profile=None):
    """Start the local AI services."""
    print("Starting local AI services...")
    cmd = ["docker", "compose", "-p", "localai"]
    if profile and profile != "none":
        cmd.extend(["--profile", profile])
    cmd.extend(["-f", "docker-compose.yml", "up", "-d"])
    run_command(cmd)

def generate_searxng_secret_key():
    """Generate a secret key for SearXNG based on the current platform."""
    print("Checking SearXNG settings...")
    settings_path = os.path.join("searxng", "settings.yml")
    settings_base_path = os.path.join("searxng", "settings-base.yml")
    if not os.path.exists(settings_base_path):
        print(f"Warning: SearXNG base settings file not found at {settings_base_path}")
        return
    if not os.path.exists(settings_path):
        print(f"SearXNG settings.yml not found. Creating from {settings_base_path}...")
        try:
            shutil.copyfile(settings_base_path, settings_path)
            print(f"Created {settings_path} from {settings_base_path}")
        except Exception as e:
            print(f"Error creating settings.yml: {e}")
            return
    else:
        print(f"SearXNG settings.yml already exists at {settings_path}")
    print("Generating SearXNG secret key...")
    system = platform.system()
    try:
        if system == "Windows":
            print("Detected Windows platform, using PowerShell...")
            ps_command = [
                "powershell", "-Command",
                "$randomBytes = New-Object byte[] 32; " +
                "(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($randomBytes); " +
                "$secretKey = -join ($randomBytes | ForEach-Object { \"{0:x2}\" -f $_ }); " +
                "(Get-Content searxng/settings.yml) -replace 'ultrasecretkey', $secretKey | Set-Content searxng/settings.yml"
            ]
            subprocess.run(ps_command, check=True)
        elif system == "Darwin":
            print("Detected macOS platform, using sed...")
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", "", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)
        else:
            print("Detected Linux/Unix platform, using sed...")
            openssl_cmd = ["openssl", "rand", "-hex", "32"]
            random_key = subprocess.check_output(openssl_cmd).decode('utf-8').strip()
            sed_cmd = ["sed", "-i", f"s|ultrasecretkey|{random_key}|g", settings_path]
            subprocess.run(sed_cmd, check=True)
        print("SearXNG secret key generated successfully.")
    except Exception as e:
        print(f"Error generating SearXNG secret key: {e}")
        print("Manually generate using: sed -i \"s|ultrasecretkey|$(openssl rand -hex 32)|g\" searxng/settings.yml")

def check_and_fix_docker_compose_for_searxng():
    """Check and modify docker-compose.yml for SearXNG first run."""
    docker_compose_path = "docker-compose.yml"
    if not os.path.exists(docker_compose_path):
        print(f"Warning: Docker Compose file not found at {docker_compose_path}")
        return
    try:
        with open(docker_compose_path, 'r') as file:
            content = file.read()
        is_first_run = True
        try:
            container_check = subprocess.run(
                ["docker", "ps", "--filter", "name=searxng", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True
            )
            searxng_containers = container_check.stdout.strip().split('\n')
            if any(container for container in searxng_containers if container):
                container_name = next(container for container in searxng_containers if container)
                print(f"Found running SearXNG container: {container_name}")
                container_check = subprocess.run(
                    ["docker", "exec", container_name, "sh", "-c", "[ -f /etc/searxng/uwsgi.ini ] && echo 'found' || echo 'not_found'"],
                    capture_output=True, text=True, check=True
                )
                if "found" in container_check.stdout:
                    print("Found uwsgi.ini - not first run")
                    is_first_run = False
                else:
                    print("uwsgi.ini not found - first run")
            else:
                print("No SearXNG container - assuming first run")
        except Exception as e:
            print(f"Error checking container: {e} - assuming first run")
        if is_first_run and "cap_drop: - ALL" in content:
            print("First run for SearXNG. Removing 'cap_drop: - ALL'...")
            modified_content = content.replace("cap_drop: - ALL", "# cap_drop: - ALL  # Commented for first run")
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)
            print("Re-add 'cap_drop: - ALL' after first run for security.")
        elif not is_first_run and "# cap_drop: - ALL  # Commented for first run" in content:
            print("SearXNG initialized. Re-enabling 'cap_drop: - ALL'...")
            modified_content = content.replace("# cap_drop: - ALL  # Commented for first run", "cap_drop: - ALL")
            with open(docker_compose_path, 'w') as file:
                file.write(modified_content)
    except Exception as e:
        print(f"Error modifying docker-compose.yml for SearXNG: {e}")

def main():
    parser = argparse.ArgumentParser(description='Start the local AI and Supabase services.')
    parser.add_argument('--profile', choices=['cpu', 'gpu-nvidia', 'gpu-amd', 'none'], default='cpu',
                       help='Profile to use for Docker Compose (default: cpu)')
    args = parser.parse_args()

    clone_supabase_repo()
    prepare_supabase_env()
    create_docker_network()
    generate_searxng_secret_key()
    check_and_fix_docker_compose_for_searxng()
    stop_existing_containers()
    start_supabase()
    print("Waiting for Supabase to initialize...")
    time.sleep(10)
    start_local_ai(args.profile)

if __name__ == "__main__":
    main()
