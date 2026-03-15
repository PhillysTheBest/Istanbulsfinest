import subprocess
import sys
import os
import re
import platform

# --- CONFIGURATION ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ANCHOR_DIR_NAME = "skill_registry"
INTEGRATION_FILE = os.path.join(PROJECT_ROOT, "solana_integration.py")

def run_anchor_command(command: str):
    """
    Runs an Anchor/Solana command. 
    If on Windows, it wraps the command in 'wsl' to execute it in the Linux subsystem.
    """
    if platform.system() == "Windows":
        # Convert absolute path to WSL format (e.g., C:\foo -> /mnt/c/foo)
        win_path = os.path.abspath(os.path.join(PROJECT_ROOT, ANCHOR_DIR_NAME))
        wsl_path = win_path.replace('\\', '/').replace('C:', '/mnt/c').replace('c:', '/mnt/c')
        
        print(f"\n>>> [WSL] Running: {command}")
        # Run via WSL bash
        return subprocess.run(
            ["wsl", "bash", "-c", f"cd {wsl_path} && {command}"],
            capture_output=True,
            text=True
        )
    else:
        # Already on Linux/Ubuntu
        print(f"\n>>> Running: {command}")
        return subprocess.run(
            command.split(),
            cwd=os.path.join(PROJECT_ROOT, ANCHOR_DIR_NAME),
            capture_output=True,
            text=True
        )

def sync_program_id():
    """Extracts the Program ID from Anchor and updates solana_integration.py."""
    print("\n>>> Synchronizing Program ID from WSL...")
    
    result = run_anchor_command("anchor keys list")
    
    if result.returncode != 0:
        print(f"ERROR: Could not fetch keys. Is Anchor installed in WSL?\n{result.stderr}")
        return False

    output = result.stdout
    # Extract ID using regex (e.g., "skill_registry: Fo6o8h...")
    match = re.search(r"skill_registry:\s+([A-Za-z0-9]+)", output)
    if not match:
        print("ERROR: Could not find Program ID in 'anchor keys list' output.")
        return False
    
    new_id = match.group(1)
    print(f"Detected Program ID: {new_id}")

    # Update solana_integration.py
    with open(INTEGRATION_FILE, "r") as f:
        content = f.read()

    # Regex to replace the PROGRAM_ID line
    updated_content = re.sub(
        r'PROGRAM_ID = Pubkey\.from_string\("[A-Za-z0-9]+"\)',
        f'PROGRAM_ID = Pubkey.from_string("{new_id}")',
        content
    )

    with open(INTEGRATION_FILE, "w") as f:
        f.write(updated_content)

    print(f"Successfully updated {os.path.basename(INTEGRATION_FILE)} with new Program ID.")
    return True

def main():
    print("="*50)
    print(" ISTANBULSFINEST - UNIFIED STARTUP PIPELINE ")
    print("="*50)

    # 1. Ask if deployment is needed
    do_deploy = input("\nDo you want to build and deploy the Solana contract? (y/n): ").lower().strip() == 'y'

    if do_deploy:
        # Step A: Anchor Build
        build_res = run_anchor_command("anchor build")
        if build_res.returncode != 0:
            print(f"Build failed:\n{build_res.stdout}\n{build_res.stderr}")
            sys.exit(1)

        # Step B: Anchor Deploy (Targeting Devnet)
        deploy_res = run_anchor_command("anchor deploy --provider.cluster devnet")
        if deploy_res.returncode != 0:
            print(f"Deploy failed:\n{deploy_res.stdout}\n{deploy_res.stderr}")
            sys.exit(1)

        # Step C: Sync ID
        if not sync_program_id():
            sys.exit(1)
    else:
        print("\nSkipping deployment. Using existing Program ID in solana_integration.py.")

    # 2. Start FastAPI Server
    print("\n" + "="*50)
    print(" STARTING FASTAPI BACKEND SERVER ")
    print("="*50)
    
    try:
        # uvicorn runs directly on Windows
        subprocess.call("python -m uvicorn backend.app:app --reload", shell=True, cwd=PROJECT_ROOT)
    except KeyboardInterrupt:
        print("\nSystem shut down.")

if __name__ == "__main__":
    main()
