import os
import json
import time
from base64 import b64decode
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.signature import Signature
from solana.rpc.types import TxOpts
from dotenv import load_dotenv
import hashlib

load_dotenv()

# --- CONSTANTS ---
# Make sure this matches your deployed program ID from anchor deploy
PROGRAM_ID = Pubkey.from_string("Fo6o8hYUm45dMK1fatMMGArptyKgD4iAB6GE9cpTWbUC")

def get_instruction_discriminator(name: str) -> bytes:
    """Calculates the 8-byte Anchor discriminator for a function name."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]

class SkillRegistryClient:
    def __init__(self, rpc_url="https://api.devnet.solana.com"):
        self.client = Client(rpc_url)
        
        # Load the SAME wallet used by the CLI (id.json) copied to wallet.json
        wallet_path = os.path.join(os.path.dirname(__file__), "wallet.json")
        try:
            with open(wallet_path, "r") as f:
                keypair_json = f.read()
            self.authority = Keypair.from_json(keypair_json)
            print(f"Loaded Authority Wallet: {self.authority.pubkey()}")
        except Exception as e:
            print(f"Failed to load wallet: {e}")
            self.authority = Keypair() # Fallback

    def get_profile_pda(self, candidate_pubkey: Pubkey):
        pda, bump = Pubkey.find_program_address(
            [b"profile", bytes(candidate_pubkey)],
            PROGRAM_ID
        )
        return pda, bump

    def issue_skill_passport(self, candidate_pubkey_str: str, skill_tree_hash: str):
        candidate_pubkey = Pubkey.from_string(candidate_pubkey_str)
        profile_pda, bump = self.get_profile_pda(candidate_pubkey)
        
        discriminator = get_instruction_discriminator("initialize_profile")
        hash_bytes = skill_tree_hash.encode('utf-8')
        instruction_data = discriminator + len(hash_bytes).to_bytes(4, 'little') + hash_bytes

        accounts = [
            AccountMeta(pubkey=profile_pda, is_signer=False, is_writable=True),
            AccountMeta(pubkey=candidate_pubkey, is_signer=False, is_writable=False), 
            AccountMeta(pubkey=self.authority.pubkey(), is_signer=True, is_writable=True), 
            AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        ]

        recent_blockhash = self.client.get_latest_blockhash().value.blockhash
        message = MessageV0.try_compile(
            payer=self.authority.pubkey(),
            instructions=[Instruction(PROGRAM_ID, instruction_data, accounts)],
            address_lookup_table_accounts=[],
            recent_blockhash=recent_blockhash
        )
        transaction = VersionedTransaction(message, [self.authority])
        
        try:
            print("Simulating transaction to find errors...")
            
            # 1. Simulate first to get logs
            sim_result = self.client.simulate_transaction(transaction)
            
            if sim_result.value.err:
                print(f"[FAILED] Simulation Error: {sim_result.value.err}")
                print("Log Messages:")
                for log in sim_result.value.logs:
                    print(f"  {log}")
                return None
            
            print("Simulation successful! Regenerating fresh blockhash...")
            recent_blockhash = self.client.get_latest_blockhash().value.blockhash
            
            # Rebuild message and transaction with fresh blockhash
            message = MessageV0.try_compile(
                payer=self.authority.pubkey(),
                instructions=[Instruction(PROGRAM_ID, instruction_data, accounts)],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash
            )
            transaction = VersionedTransaction(message, [self.authority])
            
            # We use skip_preflight=False because we know simulation passed.
            from solana.rpc.commitment import Confirmed
            opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            
            result = self.client.send_raw_transaction(bytes(transaction), opts=opts)
            
            print(f"Transaction Sent! Signature: {result.value}")
            
            time.sleep(2)  # Bug 1: Give the validator time to confirm
            
            return str(result.value)
            
        except Exception as e:
            print(f"[FAILED] Blockchain Error: {str(e)}")
            return None

    def check_transaction_status(self, tx_sig_str):
        print(f"Checking status for: {tx_sig_str}")
        time.sleep(2)  # Bug 3: Wait before checking
        from solders.signature import Signature
        from solana.rpc.commitment import Confirmed
        sig = Signature.from_string(tx_sig_str)
        
        # Use get_signature_statuses with Confirmed commitment
        status_resp = self.client.get_signature_statuses([sig])
        
        if status_resp.value[0]:
            if status_resp.value[0].err:
                print(f"Transaction FAILED: {status_resp.value[0].err}")
            else:
                print("Transaction CONFIRMED on chain (Success).")
        else:
            print("Transaction not found on chain.")

    def verify_candidate_profile(self, candidate_pubkey_str: str, db_skill_hash: str = None):
        candidate_pubkey = Pubkey.from_string(candidate_pubkey_str)
        profile_pda, _ = self.get_profile_pda(candidate_pubkey)
        
        print(f"Verifying profile at PDA: {profile_pda}")
        
        try:
            # 1. Fetch Account with Confirmed commitment (sync with transaction)
            from solana.rpc.commitment import Confirmed
            response = self.client.get_account_info(profile_pda, commitment=Confirmed)
            
            if not response.value:
                return {"status": "NOT_FOUND", "message": "No on-chain profile found."}
            
            # 2. Decode Data (handles both raw bytes and legacy base64 list format)
            raw_data = response.value.data
            if isinstance(raw_data, bytes):
                data = raw_data
            else:
                data = b64decode(raw_data[0])
            
            # 3. Parse Binary Layout (Borsh)
            # Offset 0-8: Discriminator
            # Offset 8-40: Owner (32)
            owner_on_chain = Pubkey.from_bytes(data[8:40])
            
            # Offset 40-72: Authority (32)
            authority_on_chain = Pubkey.from_bytes(data[40:72])
            
            # Offset 72-76: String Length (4 bytes)
            hash_len = int.from_bytes(data[72:76], 'little')
            
            # Safety Check
            expected_min_len = 76 + hash_len + 1
            if len(data) < expected_min_len:
                 return {"status": "ERROR", "message": "Data corruption: Data too short"}

            # Offset 76+: The Hash String
            on_chain_hash = data[76 : 76 + hash_len].decode('utf-8')
            
            # Final Byte: Is Verified
            is_verified = bool(data[76 + hash_len])
            
            # 4. Logic Check
            status = "VERIFIED"
            if db_skill_hash and on_chain_hash != db_skill_hash:
                status = "TAMPERED"
            
            authority_match = (authority_on_chain == self.authority.pubkey())
            
            return {
                "status": status,
                "on_chain_hash": on_chain_hash,
                "db_hash": db_skill_hash,
                "is_verified": is_verified,
                "owner": str(owner_on_chain),
                "authority": str(authority_on_chain),
                "authority_match": authority_match
            }
            
        except IndexError:
            return {"status": "ERROR", "message": "Failed to parse account data (IndexError)"}
        except Exception as e:
            return {"status": "ERROR", "message": f"Unexpected Error: {str(e)}"}

if __name__ == "__main__":
    registry = SkillRegistryClient()
    
    # Check balance
    balance_resp = registry.client.get_balance(registry.authority.pubkey())
    balance = balance_resp.value if balance_resp.value is not None else 0
    print(f"Wallet Balance: {balance / 1000000000} SOL")

    if balance == 0:
        print("Error: Wallet has 0 SOL. Cannot proceed.")
        exit()

    # 2. Define a test candidate
    from solders.keypair import Keypair
    test_candidate = Keypair()
    test_candidate_pubkey = str(test_candidate.pubkey())
    test_hash = "f3e9b7a195e...sha256"

    # 3. ISSUE THE PASSPORT
    print(f"\n--- Issuing Passport for {test_candidate_pubkey} ---")
    tx_sig = registry.issue_skill_passport(test_candidate_pubkey, test_hash)

    if tx_sig:
        print(f"Transaction Signature: {tx_sig}")
        
        # --- NEW CHECK ---
        registry.check_transaction_status(tx_sig)
        # -----------------
        
        print("\n--- Verifying Profile ---")
        result = registry.verify_candidate_profile(test_candidate_pubkey, test_hash)
        print(json.dumps(result, indent=4))
    else:
        print("Failed to issue passport.")