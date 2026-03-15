use anchor_lang::prelude::*;

declare_id!("Fo6o8hYUm45dMK1fatMMGArptyKgD4iAB6GE9cpTWbUC");

#[program]
pub mod skill_registry {
    use super::*;

    pub fn initialize_profile(ctx: Context<InitializeProfile>, skill_hash: String) -> Result<()> {
        let profile = &mut ctx.accounts.profile;
        profile.owner = ctx.accounts.owner.key();
        profile.authority = ctx.accounts.authority.key();
        profile.skill_hash = skill_hash;
        profile.is_verified = true;
        Ok(())
    }
}

#[account]
pub struct SkillProfile {
    pub owner: Pubkey,       // 32 bytes
    pub authority: Pubkey,   // 32 bytes
    pub skill_hash: String,  // 4 bytes (prefix) + 64 bytes (data) = 68 bytes
    pub is_verified: bool,   // 1 byte
}

#[derive(Accounts)]
#[instruction(skill_hash: String)]
pub struct InitializeProfile<'info> {
    #[account(
        init, 
        payer = authority, 
        // Space Calc: 8 (discrim) + 32 (owner) + 32 (auth) + 4 (str prefix) + 64 (str data) + 1 (bool)
        space = 8 + 32 + 32 + 4 + 64 + 1,
        seeds = [b"profile", owner.key().as_ref()],
        bump
    )]
    pub profile: Account<'info, SkillProfile>,
    
    /// CHECK: The candidate's wallet address. We only need the public key, 
    /// we don't verify the signature because the Backend (Authority) pays.
    pub owner: UncheckedAccount<'info>,
    
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}