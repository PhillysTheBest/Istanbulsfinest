use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS"); // Placeholder ID for devnet

// In a real production environment, this would be your AI backend's public key.
const EXPECTED_BACKEND_PUBKEY: Pubkey = pubkey!("BackendWalletAddress111111111111111111111111");

#[program]
pub mod skill_registry {
    use super::*;

    /// Initialize a new skill profile for a candidate.
    /// This uses a PDA to ensure only ONE profile exists per candidate.
    /// SECURITY: The Backend Authority MUST sign this transaction.
    pub fn initialize_profile(ctx: Context<InitializeProfile>, skill_hash: String) -> Result<()> {
        let profile = &mut ctx.accounts.profile;
        profile.owner = ctx.accounts.owner.key();
        profile.authority = ctx.accounts.authority.key(); // The verified backend key
        profile.skill_hash = skill_hash;
        profile.is_verified = true;
        profile.bump = ctx.bumps.profile;
        
        msg!("Profile initialized via PDA for candidate: {}", profile.owner);
        Ok(())
    }

    /// Update the skill tree hash. 
    /// SECURITY: Only the Backend Authority is allowed to call this.
    pub fn update_profile(ctx: Context<UpdateProfile>, new_skill_hash: String) -> Result<()> {
        let profile = &mut ctx.accounts.profile;
        profile.skill_hash = new_skill_hash;
        
        msg!("Profile updated by verified authority for candidate: {}", profile.owner);
        Ok(())
    }
}

#[account]
pub struct SkillProfile {
    pub owner: Pubkey,       // Candidate's wallet
    pub authority: Pubkey,   // Istanbulsfinest backend AI wallet
    pub skill_hash: String,  // SHA-256 hash of the Skill Tree
    pub is_verified: bool,   // Verification status flag
    pub bump: u8,            // Store bump for PDA validation
}

#[derive(Accounts)]
pub struct InitializeProfile<'info> {
    // PDA derivation ensuring 1:1 mapping: [b"profile", owner_pubkey]
    #[account(
        init, 
        payer = owner, 
        space = 8 + 32 + 32 + 64 + 1 + 1, 
        seeds = [b"profile", owner.key().as_ref()],
        bump
    )] 
    pub profile: Account<'info, SkillProfile>,
    
    #[account(mut)]
    pub owner: Signer<'info>, // Candidate wallet paying for account creation
    
    // SECURITY FIX: Authority must be a Signer AND match our known backend key.
    #[account(
        constraint = authority.key() == EXPECTED_BACKEND_PUBKEY @ CustomError::InvalidAuthority
    )]
    pub authority: Signer<'info>, 
    
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateProfile<'info> {
    // SECURITY CHECK: Matches the 'authority' stored in the account with the Signer.
    #[account(mut, has_one = authority)]
    pub profile: Account<'info, SkillProfile>,
    pub authority: Signer<'info>, 
}

#[error_code]
pub enum CustomError {
    #[msg("Only the official Istanbulsfinest backend authority can initialize or update profiles.")]
    InvalidAuthority,
}
