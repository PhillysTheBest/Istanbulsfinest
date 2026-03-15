import asyncio
import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from database import get_skills_profile_collection
from solana_integration import SkillRegistryClient

# --- MODELS ---

class VerificationResult(BaseModel):
    status: str = Field(..., description="Status of the verification (VERIFIED, TAMPERED, PENDING, NOT_FOUND, BLOCKCHAIN_ERROR)")
    candidate_wallet: str
    skill_hash_match: bool = False
    on_chain_hash: Optional[str] = None
    db_hash: Optional[str] = None
    solana_tx_signature: Optional[str] = None
    authority_match: bool = False
    checked_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    message: Optional[str] = None

class BatchVerifyRequest(BaseModel):
    wallets: List[str]

class VerificationReport(BaseModel):
    report_generated_at: str = Field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    total_candidates: int
    verified: int
    tampered: int
    pending: int
    not_found: int
    blockchain_errors: int
    results: List[VerificationResult]

# --- ROUTER ---

router = APIRouter(prefix="/verify", tags=["Verification"])

# --- CORE LOGIC ---

async def verify_candidate(candidate_wallet: str) -> VerificationResult:
    """
    Standalone async function to cross-check a candidate's hash against 
    both MongoDB and the Solana blockchain.
    """
    # --- WEB2 ---
    collection = get_skills_profile_collection()
    doc = collection.find_one({"candidate_wallet": candidate_wallet})
    
    if not doc:
        return VerificationResult(
            status="NOT_FOUND",
            candidate_wallet=candidate_wallet,
            message="Candidate has no profile in the system"
        )
    
    db_hash = doc.get("skill_hash")
    solana_tx_sig = doc.get("solana_tx_signature")
    blockchain_status = doc.get("blockchain_status")
    
    if blockchain_status == "PENDING":
        return VerificationResult(
            status="PENDING",
            candidate_wallet=candidate_wallet,
            message="Profile not yet anchored to blockchain",
            db_hash=db_hash
        )

    # --- WEB3 ---
    try:
        registry = SkillRegistryClient()
        # Call the integration layer to fetch and verify on-chain data
        # verify_candidate_profile returns: {status, on_chain_hash, is_verified, authority_match}
        web3_result = registry.verify_candidate_profile(candidate_wallet, db_hash)
        
        on_chain_hash = web3_result.get("on_chain_hash")
        authority_match = web3_result.get("authority_match", False)
        
        # Check for discrepancies
        if web3_result["status"] == "VERIFIED":
            return VerificationResult(
                status="VERIFIED",
                candidate_wallet=candidate_wallet,
                skill_hash_match=True,
                on_chain_hash=on_chain_hash,
                db_hash=db_hash,
                solana_tx_signature=solana_tx_sig,
                authority_match=authority_match
            )
        elif web3_result["status"] == "TAMPERED":
            return VerificationResult(
                status="TAMPERED",
                candidate_wallet=candidate_wallet,
                skill_hash_match=False,
                on_chain_hash=on_chain_hash,
                db_hash=db_hash,
                solana_tx_signature=solana_tx_sig,
                authority_match=authority_match,
                message="On-chain hash does not match MongoDB record!"
            )
        else:
            # Catch cases like "NOT_FOUND" on-chain despite being marked "CONFIRMED" in DB
            return VerificationResult(
                status="BLOCKCHAIN_ERROR",
                candidate_wallet=candidate_wallet,
                message=web3_result.get("message", "Unknown blockchain error"),
                db_hash=db_hash,
                solana_tx_signature=solana_tx_sig
            )
            
    except Exception as e:
        return VerificationResult(
            status="BLOCKCHAIN_ERROR",
            candidate_wallet=candidate_wallet,
            message=str(e),
            db_hash=db_hash,
            solana_tx_signature=solana_tx_sig
        )

async def batch_verify_candidates(wallet_list: List[str]) -> List[VerificationResult]:
    """Concurrent batch verification using asyncio.gather."""
    tasks = [verify_candidate(w) for w in wallet_list]
    return await asyncio.gather(*tasks)

def generate_verification_report(results: List[VerificationResult]) -> VerificationReport:
    """Summarizes a list of verification results into a statistics report."""
    summary = {
        "verified": 0,
        "tampered": 0,
        "pending": 0,
        "not_found": 0,
        "blockchain_errors": 0
    }
    
    for r in results:
        status_key = r.status.lower()
        if status_key in summary:
            summary[status_key] += 1
            
    return VerificationReport(
        total_candidates=len(results),
        results=results,
        **summary
    )

# --- ROUTES ---

@router.get("/{candidate_wallet}", response_model=VerificationResult)
async def get_verification(candidate_wallet: str = Path(..., description="The candidate's Solana public key")):
    """Verify a single candidate's skill tree hash."""
    result = await verify_candidate(candidate_wallet)
    
    # Map internal status to HTTP codes
    if result.status == "NOT_FOUND":
        return JSONResponse(status_code=404, content=result.dict())
    elif result.status == "PENDING":
        return JSONResponse(status_code=202, content=result.dict())
    elif result.status == "BLOCKCHAIN_ERROR":
        return JSONResponse(status_code=500, content=result.dict())
    
    return result

@router.post("/batch", response_model=VerificationReport)
async def post_batch_verification(request: BatchVerifyRequest):
    """Batch verify multiple candidates and generate a summary report."""
    results = await batch_verify_candidates(request.wallets)
    report = generate_verification_report(results)
    return report

# --- USAGE IN backend/app.py ---
# from verification import router as verification_router
# app.include_router(verification_router)
