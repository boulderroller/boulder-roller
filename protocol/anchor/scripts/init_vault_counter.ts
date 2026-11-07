import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
} from "@solana/web3.js";
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";

const DEVNET_ADDRESSES = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../addresses.devnet.json"), "utf-8")
);
const PROGRAM_ID = new PublicKey(
  process.env.BOULDER_ROLLERS_PROGRAM_ID || DEVNET_ADDRESSES.programs.boulder_rollers
);
const VAULT_COUNTER_SEED = Buffer.from("vault_counter");

// Load deployer keypair
const deployerPath = path.join(
  process.env.HOME!,
  ".config/solana/devnet-deployer.json"
);
const deployerJson = JSON.parse(fs.readFileSync(deployerPath, "utf-8"));
const deployer = Keypair.fromSecretKey(Uint8Array.from(deployerJson));

// Anchor instruction discriminator: first 8 bytes of SHA256("global:<instruction_name>")
function getInstructionDiscriminator(name: string): Buffer {
  const hash = crypto.createHash("sha256");
  hash.update(`global:${name}`);
  return hash.digest().slice(0, 8);
}

async function main() {
  const connection = new Connection(
    process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com",
    "confirmed"
  );

  console.log("Deployer:", deployer.publicKey.toBase58());
  console.log("Program:", PROGRAM_ID.toBase58());

  // Derive vault counter PDA
  const [vaultCounterPda, bump] = PublicKey.findProgramAddressSync(
    [VAULT_COUNTER_SEED],
    PROGRAM_ID
  );
  console.log("Vault Counter PDA:", vaultCounterPda.toBase58(), "bump:", bump);

  // Check if already initialized
  const existingAccount = await connection.getAccountInfo(vaultCounterPda);
  if (existingAccount) {
    console.log("Vault counter already initialized!");
    console.log("Data:", existingAccount.data.toString("hex"));
    return;
  }

  // Build instruction
  const discriminator = getInstructionDiscriminator("initialize_vault_counter");
  console.log("Discriminator:", discriminator.toString("hex"));

  const ix = new TransactionInstruction({
    programId: PROGRAM_ID,
    keys: [
      { pubkey: vaultCounterPda, isSigner: false, isWritable: true },
      { pubkey: deployer.publicKey, isSigner: true, isWritable: true },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
    ],
    data: discriminator,
  });

  const tx = new Transaction().add(ix);

  console.log("Sending transaction...");
  const sig = await sendAndConfirmTransaction(connection, tx, [deployer]);
  console.log("Success! Signature:", sig);

  // Verify
  const account = await connection.getAccountInfo(vaultCounterPda);
  console.log("Vault counter initialized! Data:", account?.data.toString("hex"));
}

main().catch(console.error);
