/**
 * Create Token Metadata for DUNG token on Solana
 * Uses Metaplex Token Metadata v3
 *
 * Usage: npx ts-node scripts/create_token_metadata.ts
 */

import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
  SystemProgram,
} from "@solana/web3.js";
import * as fs from "fs";
import * as path from "path";
import "dotenv/config";

// Configuration
const DUNG_MINT = new PublicKey("EehbpgVwgsFLgZmUFkAA6JU4Z9Uif2muY1pbHnSQQv2P");
const RPC_URL = process.env.SOLANA_RPC_URL || "https://api.devnet.solana.com";

// Token Metadata Program ID
const TOKEN_METADATA_PROGRAM_ID = new PublicKey(
  "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
);

// Metadata for DUNG token
const TOKEN_NAME = "DUNG";
const TOKEN_SYMBOL = "DUNG";
const TOKEN_URI = "https://boulderrollers.com/metadata/dung.json";

function getMetadataPDA(mint: PublicKey): PublicKey {
  const [pda] = PublicKey.findProgramAddressSync(
    [
      Buffer.from("metadata"),
      TOKEN_METADATA_PROGRAM_ID.toBuffer(),
      mint.toBuffer(),
    ],
    TOKEN_METADATA_PROGRAM_ID
  );
  return pda;
}

function loadKeypair(filePath: string): Keypair {
  const resolved = filePath.startsWith("~")
    ? path.join(process.env.HOME || "", filePath.slice(1))
    : filePath;
  const secretKey = JSON.parse(fs.readFileSync(resolved, "utf-8"));
  return Keypair.fromSecretKey(Uint8Array.from(secretKey));
}

// Build CreateMetadataAccountV3 instruction manually
function createMetadataInstruction(
  metadataPDA: PublicKey,
  mint: PublicKey,
  mintAuthority: PublicKey,
  payer: PublicKey,
  updateAuthority: PublicKey,
  name: string,
  symbol: string,
  uri: string
): TransactionInstruction {
  // Instruction discriminator for CreateMetadataAccountV3
  const CREATE_METADATA_V3_DISCRIMINATOR = 33;

  // Serialize the data
  const nameBytes = Buffer.from(name);
  const symbolBytes = Buffer.from(symbol);
  const uriBytes = Buffer.from(uri);

  // Build data buffer
  // Format: discriminator(1) + name_len(4) + name + symbol_len(4) + symbol + uri_len(4) + uri + seller_fee(2) + creators_option(1) + collection_option(1) + uses_option(1) + is_mutable(1) + collection_details_option(1)
  const dataLen = 1 + 4 + nameBytes.length + 4 + symbolBytes.length + 4 + uriBytes.length + 2 + 1 + 1 + 1 + 1 + 1;
  const data = Buffer.alloc(dataLen);
  let offset = 0;

  // Discriminator
  data.writeUInt8(CREATE_METADATA_V3_DISCRIMINATOR, offset);
  offset += 1;

  // Name (borsh string: u32 length + bytes)
  data.writeUInt32LE(nameBytes.length, offset);
  offset += 4;
  nameBytes.copy(data, offset);
  offset += nameBytes.length;

  // Symbol
  data.writeUInt32LE(symbolBytes.length, offset);
  offset += 4;
  symbolBytes.copy(data, offset);
  offset += symbolBytes.length;

  // URI
  data.writeUInt32LE(uriBytes.length, offset);
  offset += 4;
  uriBytes.copy(data, offset);
  offset += uriBytes.length;

  // Seller fee basis points (0)
  data.writeUInt16LE(0, offset);
  offset += 2;

  // Creators (None = 0)
  data.writeUInt8(0, offset);
  offset += 1;

  // Collection (None = 0)
  data.writeUInt8(0, offset);
  offset += 1;

  // Uses (None = 0)
  data.writeUInt8(0, offset);
  offset += 1;

  // Is mutable (true = 1)
  data.writeUInt8(1, offset);
  offset += 1;

  // Collection details (None = 0)
  data.writeUInt8(0, offset);

  return new TransactionInstruction({
    keys: [
      { pubkey: metadataPDA, isSigner: false, isWritable: true },
      { pubkey: mint, isSigner: false, isWritable: false },
      { pubkey: mintAuthority, isSigner: true, isWritable: false },
      { pubkey: payer, isSigner: true, isWritable: true },
      { pubkey: updateAuthority, isSigner: false, isWritable: false },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
    ],
    programId: TOKEN_METADATA_PROGRAM_ID,
    data,
  });
}

async function main() {
  console.log("=== DUNG Token Metadata Creation ===\n");

  // Load payer keypair
  const payerPath = process.env.SOLANA_PAYER_PATH || "./payer-devnet.json";
  const payer = loadKeypair(payerPath);
  console.log("Payer:", payer.publicKey.toBase58());

  // Connect to cluster
  const connection = new Connection(RPC_URL, "confirmed");
  console.log("RPC:", RPC_URL);
  console.log("Mint:", DUNG_MINT.toBase58());

  // Get metadata PDA
  const metadataPDA = getMetadataPDA(DUNG_MINT);
  console.log("Metadata PDA:", metadataPDA.toBase58());

  // Check if metadata already exists
  const existingMetadata = await connection.getAccountInfo(metadataPDA);
  if (existingMetadata) {
    console.log("\n Metadata account already exists!");
    console.log("Size:", existingMetadata.data.length, "bytes");
    return;
  }

  // Create the instruction
  const createMetadataIx = createMetadataInstruction(
    metadataPDA,
    DUNG_MINT,
    payer.publicKey,
    payer.publicKey,
    payer.publicKey,
    TOKEN_NAME,
    TOKEN_SYMBOL,
    TOKEN_URI
  );

  // Build and send transaction
  const tx = new Transaction().add(createMetadataIx);

  console.log("\nSending transaction...");
  try {
    const sig = await sendAndConfirmTransaction(connection, tx, [payer], {
      commitment: "confirmed",
    });
    console.log("\n Metadata created successfully!");
    console.log("Signature:", sig);
    console.log(`\nView on Solscan: https://solscan.io/token/${DUNG_MINT.toBase58()}?cluster=devnet`);
  } catch (err) {
    console.error("\n Failed to create metadata:", err);
    throw err;
  }
}

main().catch(console.error);
