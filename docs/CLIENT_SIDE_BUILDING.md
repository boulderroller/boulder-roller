# Client-Side Transaction Building

For power users who want to build transactions directly without the backend, you can use the published IDL to interact with the Boulder Rollers Solana programs.

## IDL Location

The IDL is available at:
- **Production:** `https://app.boulderroller.xyz/idl/boulder_rollers.json`
- **Local:** `web/portal/public/idl/boulder_rollers.json`

## Program IDs

| Program | Address |
|---------|---------|
| boulder_rollers | `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH` |
| *(archived)* dung_mint | `A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ` |
| *(archived)* proof_verifier | `Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC` |

## TypeScript Usage

```typescript
import * as anchor from '@coral-xyz/anchor';
import { PublicKey, Connection } from '@solana/web3.js';

// Load IDL
const idl = await (await fetch('https://app.boulderroller.xyz/idl/boulder_rollers.json')).json();

// Create program
const programId = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const connection = new Connection('https://api.devnet.solana.com');
const provider = new anchor.AnchorProvider(connection, wallet, {});
const program = new anchor.Program(idl, programId, provider);

// Derive PDAs
function findUserStatePda(user: PublicKey) {
  return PublicKey.findProgramAddressSync(
    [Buffer.from('user'), user.toBuffer()],
    programId,
  );
}

function findVaultPda(vaultId: number) {
  const idBuffer = Buffer.alloc(8);
  idBuffer.writeBigUInt64LE(BigInt(vaultId));
  return PublicKey.findProgramAddressSync(
    [Buffer.from('vault'), idBuffer],
    programId,
  );
}

function findVaultStakePda(user: PublicKey, vaultId: number) {
  const idBuffer = Buffer.alloc(8);
  idBuffer.writeBigUInt64LE(BigInt(vaultId));
  return PublicKey.findProgramAddressSync(
    [Buffer.from('vault_stake'), user.toBuffer(), idBuffer],
    programId,
  );
}

function findVaultLpMintPda(vaultId: number) {
  const idBuffer = Buffer.alloc(8);
  idBuffer.writeBigUInt64LE(BigInt(vaultId));
  return PublicKey.findProgramAddressSync(
    [Buffer.from('vault_lp'), idBuffer],
    programId,
  );
}
```

## Available Instructions

### Staking

```typescript
// Stake CAL in a vault
await program.methods
  .stakeCalInVault(new BN(amount))
  .accounts({
    vault: vaultPda,
    vaultStake: vaultStakePda,
    vaultLpMint: vaultLpMintPda,
    userLpAccount: userLpAta,
    userState: userStatePda,
    user: wallet.publicKey,
    tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId,
    rent: SYSVAR_RENT_PUBKEY,
  })
  .rpc();

// Unstake CAL from a vault
await program.methods
  .unstakeCalFromVault(new BN(lpAmount))
  .accounts({
    vault: vaultPda,
    vaultStake: vaultStakePda,
    vaultLpMint: vaultLpMintPda,
    userLpAccount: userLpAta,
    userState: userStatePda,
    user: wallet.publicKey,
    tokenProgram: TOKEN_PROGRAM_ID,
  })
  .rpc();

// Harvest rewards
await program.methods
  .harvest()
  .accounts({
    vault: vaultPda,
    vaultStake: vaultStakePda,
    userDungAccount: userDungAta,
    dungMint: DUNG_MINT,
    user: wallet.publicKey,
    tokenProgram: TOKEN_PROGRAM_ID,
  })
  .rpc();
```

### Vault Creation

```typescript
// Create vault with DUNG burn
await program.methods
  .createVault(
    Array.from(signatureBytes), // 64-byte signature
    'My Climb Name',
    5000,  // vert_m * 10
    6666,  // distance_m
    750,   // avg_gradient_pct * 100
  )
  .accounts({
    vaultCounter: vaultCounterPda,
    vault: vaultPda,
    creator: wallet.publicKey,
    creatorDungAccount: userDungAta,
    dungMint: DUNG_MINT,
    tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId,
  })
  .rpc();

// Create vault with CAL + USDC
await program.methods
  .createVaultWithUsdc(
    Array.from(signatureBytes),
    'My Climb Name',
    5000,
    6666,
    750,
  )
  .accounts({
    vaultCounter: vaultCounterPda,
    vault: vaultPda,
    userState: userStatePda,
    creator: wallet.publicKey,
    creatorUsdcAccount: userUsdcAta,
    protocolUsdcAccount: protocolUsdcAta,
    usdcMint: USDC_MINT,
    tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId,
  })
  .rpc();
```

### BeetleCard Upgrade

```typescript
await program.methods
  .upgradeBeetleCard(
    cardType, // 0=Climb, 1=Steady, 2=Explorer
    targetLevel, // 2-10
  )
  .accounts({
    beetleCard: beetleCardPda,
    userState: userStatePda,
    user: wallet.publicKey,
    userDungAccount: userDungAta,
    dungMint: DUNG_MINT,
    tokenProgram: TOKEN_PROGRAM_ID,
  })
  .rpc();
```

## Token Addresses

| Token | Devnet Address |
|-------|----------------|
| DUNG Mint | (from dung_mint program state) |
| USDC Mint | `Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr` |

## Constants

```typescript
// Vault creation costs
const VAULT_CREATION_DUNG = 100_000_000_000n; // 100 DUNG (9 decimals)
const VAULT_CREATION_CAL = 1000n; // 1000 CAL
const VAULT_CREATION_USDC = 2_000_000n; // $2 USDC (6 decimals)

// Staking
const MINIMUM_STAKE = 10_000_000_000n; // 10 DUNG minimum

// BeetleCard upgrade costs: 25 * 2^(N-1) DUNG
const UPGRADE_COSTS = [
  25n,   // Level 2
  50n,   // Level 3
  100n,  // Level 4
  200n,  // Level 5
  400n,  // Level 6
  800n,  // Level 7
  1600n, // Level 8
  3200n, // Level 9
  6400n, // Level 10
].map(cost => cost * 1_000_000_000n);
```

## Error Handling

Common error codes:

| Code | Name | Description |
|------|------|-------------|
| 6000 | `AlreadyMintedToday` | CAL already credited for today |
| 6001 | `InsufficientCal` | Not enough CAL balance |
| 6002 | `InvalidName` | Vault name length invalid |
| 6003 | `InvalidDistance` | Distance too short |
| 6004 | `InvalidElevation` | Elevation gain too low |
| 6005 | `MinimumStakeRequired` | Stake below 10 DUNG minimum |
| 6023 | `SupplyCapExceeded` | Would exceed DUNG supply cap |
| 6033 | `NotOwner` | Signer doesn't own account |

## Backend vs Client-Side

| Feature | Backend API | Client-Side |
|---------|-------------|-------------|
| Transaction building | Handled for you | Build manually |
| PDA derivation | Automatic | Manual |
| Account lookup | Automatic | Manual |
| Error handling | Structured responses | Raw Anchor errors |
| Gas payer | Backend (points period) | User wallet |

**Recommendation:** Use the backend API (`/transactions/build/*`) for most users. Client-side building is for integrations, bots, or power users who need custom transaction flows.
