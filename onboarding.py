import secrets
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Path, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from solders.pubkey import Pubkey
from solders.signature import Signature
from database import get_skills_profile_collection, get_blockchain_profile_collection
from solana_integration import SkillRegistryClient

# --- MODELS ---

class NonceRequest(BaseModel):
    candidate_id: str

class NonceResponse(BaseModel):
    nonce: str
    message: str

class WalletVerifyRequest(BaseModel):
    candidate_id: str
    wallet_address: str
    signed_message: str # The signature bytes as a hex string from the frontend

class WalletVerifyResponse(BaseModel):
    status: str
    candidate_wallet: str
    blockchain_triggered: bool

class OnboardingStatus(BaseModel):
    candidate_id: str
    cv_parsed: bool
    skill_hash_ready: bool
    wallet_linked: bool
    blockchain_status: str
    next_step: str

# --- ROUTER ---

router = APIRouter(prefix="/onboard", tags=["Onboarding"])

# --- CORE LOGIC ---

def generate_wallet_nonce(candidate_id: str) -> NonceResponse:
    """ Generates a cryptographically random nonce with 5-minute TTL. """
    nonce = secrets.token_hex(16)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    
    # --- WEB2 ---
    collection = get_blockchain_profile_collection()
    # Store nonce in the BlockchainProfile document
    result = collection.update_one(
        {"user_id": candidate_id},
        {"$set": {
            "user_id": candidate_id,
            "nonce": nonce,
            "nonce_expires_at": expires_at
        }},
        upsert=True
    )
    
    # We always return the message even if we just created the document
    message = f"Sign this message to verify your Istanbulsfinest wallet ownership.\nNonce: {nonce}\nExpires in 5 minutes."
    
    return NonceResponse(nonce=nonce, message=message)

def verify_wallet_signature(candidate_id: str, wallet_address: str, signed_message_hex: str) -> WalletVerifyResponse:
    """ Verifies the signature from the wallet and links it to the profile. """
    collection = get_blockchain_profile_collection()
    doc = collection.find_one({"user_id": candidate_id})
    
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
        
    stored_nonce = doc.get("nonce")
    expires_at = doc.get("nonce_expires_at")
    
    # --- WEB2 CHECKS ---
    if not stored_nonce or not expires_at:
        raise HTTPException(status_code=400, detail="No active verification request found")
        
    if datetime.datetime.utcnow() > expires_at:
        raise HTTPException(status_code=400, detail="Verification nonce has expired")

    # --- WEB3 VERIFICATION ---
    try:
        # Reconstruct the original message
        original_message = f"Sign this message to verify your Istanbulsfinest wallet ownership.\nNonce: {stored_nonce}\nExpires in 5 minutes."
        message_bytes = original_message.encode("utf-8")
        
        # Verify using solders
        pubkey = Pubkey.from_string(wallet_address)
        signature = Signature.from_string(signed_message_hex)
        
        # solders signature verification
        if not signature.verify(pubkey, message_bytes):
            raise HTTPException(status_code=401, detail="Invalid wallet signature")
            
    except Exception as e:
        print(f"Signature Verification Error: {e}")
        raise HTTPException(status_code=401, detail="Could not verify wallet signature")

    # --- WEB2 UPDATE ---
    blockchain_triggered = False
    now = datetime.datetime.utcnow()
    
    update_fields = {
        "candidate_wallet": wallet_address,
        "wallet_verified": True,
        "wallet_linked_at": now,
        "blockchain_status": doc.get("blockchain_status", "PENDING")
    }
    
    # Remove nonce fields after use (one-time use)
    collection.update_one(
        {"user_id": candidate_id},
        {"$set": update_fields, "$unset": {"nonce": "", "nonce_expires_at": ""}}
    )

    # --- WEB3 ANCHORING TRIGGER ---
    # If the skill hash is already ready but we were waiting for the wallet
    skill_hash = doc.get("skill_hash")
    if skill_hash and doc.get("blockchain_status") == "PENDING":
        try:
            print(f"Triggering delayed anchoring for wallet: {wallet_address}")
            registry = SkillRegistryClient()
            tx_sig = registry.issue_skill_passport(wallet_address, skill_hash)
            
            if tx_sig:
                collection.update_one(
                    {"user_id": candidate_id},
                    {"$set": {
                        "solana_tx_signature": tx_sig,
                        "blockchain_status": "CONFIRMED"
                    }}
                )
                blockchain_triggered = True
        except Exception as e:
            print(f"Delayed anchoring error: {e}")

    return WalletVerifyResponse(
        status="WALLET_LINKED",
        candidate_wallet=wallet_address,
        blockchain_triggered=blockchain_triggered
    )

def get_onboarding_status(candidate_id: str) -> OnboardingStatus:
    """ Computes the candidate's current step and next required action. """
    skills_coll = get_skills_profile_collection()
    blockchain_coll = get_blockchain_profile_collection()
    
    skills_doc = skills_coll.find_one({"user_id": candidate_id})
    blockchain_doc = blockchain_coll.find_one({"user_id": candidate_id})
    
    if not skills_doc and not blockchain_doc:
        return OnboardingStatus(
            candidate_id=candidate_id,
            cv_parsed=False, skill_hash_ready=False, wallet_linked=False,
            blockchain_status="N/A",
            next_step="Upload your CV to start the verification process."
        )

    cv_parsed = skills_doc is not None
    skill_hash = blockchain_doc.get("skill_hash") if blockchain_doc else None
    skill_hash_ready = skill_hash is not None
    wallet_linked = blockchain_doc.get("wallet_verified", False) if blockchain_doc else False
    blockchain_status = blockchain_doc.get("blockchain_status", "PENDING") if blockchain_doc else "PENDING"
    
    # Dynamic Next Step Logic
    if not skill_hash_ready:
        next_step = "Wait for Gemini to finish parsing your CV skills."
    elif not wallet_linked:
        next_step = "Connect your Solana wallet to anchor your skills to the blockchain."
    elif blockchain_status == "PENDING":
        next_step = "Blockchain confirmation in progress. Check back in a few minutes."
    else:
        next_step = "Verification complete! Your skills are now permanently anchored to Solana."

    return OnboardingStatus(
        candidate_id=candidate_id,
        cv_parsed=cv_parsed,
        skill_hash_ready=skill_hash_ready,
        wallet_linked=wallet_linked,
        blockchain_status=blockchain_status,
        next_step=next_step
    )

# --- ROUTES ---

@router.post("/request-nonce", response_model=NonceResponse)
async def post_request_nonce(request: NonceRequest):
    """ Get a one-time message for the wallet to sign. """
    return generate_wallet_nonce(request.candidate_id)

@router.post("/verify-wallet", response_model=WalletVerifyResponse)
async def post_verify_wallet(request: WalletVerifyRequest):
    """ Link wallet after verifying the cryptographic signature. """
    return verify_wallet_signature(request.candidate_id, request.wallet_address, request.signed_message)

@router.get("/status/{candidate_id}", response_model=OnboardingStatus)
async def get_status(candidate_id: str = Path(..., description="The internal candidate ID")):
    """ Check the current onboarding progress. """
    return get_onboarding_status(candidate_id)
