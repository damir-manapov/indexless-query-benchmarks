"""Common utilities shared between optimizers."""

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from python_terraform import Terraform


def run_ssh_command(
    vm_ip: str, command: str, timeout: int = 300, forward_agent: bool = False
) -> tuple[int, str]:
    """Run command on remote VM via SSH.

    Args:
        vm_ip: IP address of VM to connect to
        command: Command to run on VM
        timeout: Command timeout in seconds
        forward_agent: If True, forward SSH agent for nested SSH connections
    """
    ssh_args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
    ]
    if forward_agent:
        ssh_args.append("-A")
    ssh_args.extend([f"root@{vm_ip}", command])

    result = subprocess.run(
        ssh_args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def wait_for_vm_ready(vm_ip: str, timeout: int = 300) -> bool:
    """Wait for benchmark VM to be ready (cloud-init complete)."""
    print(f"  Waiting for VM {vm_ip} to be ready...")

    start = time.time()
    while time.time() - start < timeout:
        try:
            code, _ = run_ssh_command(
                vm_ip, "test -f /root/benchmark-ready", timeout=15
            )
            if code == 0:
                print("  VM is ready!")
                return True
        except Exception as e:
            print(f"  SSH not ready yet: {e}")
        time.sleep(10)

    print(f"  Warning: VM not ready after {timeout}s, continuing anyway...")
    return False


def clear_known_hosts_on_vm(vm_ip: str) -> None:
    """Clear known_hosts on benchmark VM to avoid stale host key errors.

    When VMs are recreated, their host keys change. This causes SSH to reject
    connections due to 'host key has changed' warnings.
    """
    try:
        run_ssh_command(vm_ip, "rm -f /root/.ssh/known_hosts", timeout=10)
    except Exception:
        pass  # Ignore errors, file may not exist


def validate_vm_exists(vm_ip: str) -> bool:
    """Check if VM is actually reachable (not just in state)."""
    try:
        code, _ = run_ssh_command(vm_ip, "echo ok", timeout=10)
        return code == 0
    except Exception:
        return False


def load_results(results_path: Path) -> list[dict[str, Any]]:
    """Load results from a JSON file."""
    if results_path.exists():
        with open(results_path) as f:
            return json.load(f)
    return []


def save_results(results: list[dict[str, Any]], results_path: Path) -> None:
    """Save results to a JSON file."""
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)


def get_terraform(terraform_dir: Path) -> Terraform:
    """Get Terraform instance, initializing if needed."""
    tf_dir = str(terraform_dir)
    tf = Terraform(working_dir=tf_dir)

    # Check if init needed
    dot_terraform = terraform_dir / ".terraform"
    if not dot_terraform.exists():
        print(f"  Initializing Terraform in {tf_dir}...")
        ret_code, stdout, stderr = tf.init()
        if ret_code != 0:
            raise RuntimeError(f"Terraform init failed: {stderr}")

    return tf


def get_tf_output(tf: Terraform, name: str) -> str | None:
    """Get terraform output value, handling different return formats."""
    try:
        ret, out, err = tf.output_cmd(name)
        if ret != 0 or not out:
            return None
        # Output is JSON-formatted, strip quotes and newlines
        value = out.strip().strip('"')
        # Check if it's a valid value (not a warning message or null)
        if not value or value == "null" or value.startswith("╷") or "Warning" in value:
            return None
        return value
    except Exception:
        return None


def is_stale_state_error(stderr: str | None) -> bool:
    """Check if the error indicates stale terraform state."""
    if stderr is None:
        return False
    return "not found" in stderr.lower() or "404" in stderr


def clear_terraform_state(terraform_dir: Path) -> None:
    """Clear Terraform state files to start fresh."""
    import os

    for f in ["terraform.tfstate", "terraform.tfstate.backup"]:
        path = terraform_dir / f
        if path.exists():
            os.remove(path)
            print(f"  Removed stale state: {path}")


def destroy_all(terraform_dir: Path, cloud_name: str) -> bool:
    """Destroy all infrastructure."""
    print(f"\nDestroying all resources on {cloud_name}...")

    result = subprocess.run(
        ["terraform", "destroy", "-auto-approve"],
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Warning: Destroy may have failed: {result.stderr}")
        return False

    print("  All resources destroyed.")
    return True
