# Solana Mobile dApp Patterns — Research Report

**Date:** 2026-04-15
**Scope:** Production Solana mobile RPC patterns, SMS/Seeker SDK, @solana/web3.js in React Native, caching, wallet UX
**For:** Boulder Rollers mobile Phase A architecture decisions

## Executive Summary

Boulder Rollers' planned architecture is well-aligned with production patterns. The strongest decisions are: (1) using Privy for embedded wallets instead of relying on MWA (which has zero iOS support), (2) SQLite for persistent chain cache (the emerging best practice), (3) TanStack React Query for stale-while-revalidate, and (4) skipping `@coral-xyz/anchor` in favor of raw `getAccountInfo` + IDL-derived Borsh decoders. The biggest integration risks are: (a) `@solana/web3.js` v1 polyfill fragility in Expo — you should evaluate migrating to `@solana/kit` (v2) which is tree-shakeable and zero-dependency but requires a `SubtleCrypto` polyfill that is tricky on RN, (b) websocket subscriptions are unreliable on mobile (iOS kills background sockets) — use polling, not `accountSubscribe`, and (c) Helius rate limits at your tier will constrain aggressive polling. Your verify-chip UX (tap-to-verify, not auto-poll) is the correct pattern and will naturally stay within rate budgets. Batch your reads via `getMultipleAccounts` (max 100 per call) to minimize round trips.

## 1. Solana Mobile Stack (SMS) Overview

**What SMS provides:**
- **Mobile Wallet Adapter (MWA):** Protocol for dApp-to-wallet communication for transaction signing on Android. Uses WebSocket between dApp and wallet app. Supports authorization, signing, and sending transactions. Available for React Native, Kotlin, Java.
- **Seed Vault:** Hardware-backed keystore on Seeker/Saga for secure on-device signing (fingerprint + double-tap UX). Seeker-exclusive.
- **dApp Store:** Alternative to Google Play, crypto-friendly distribution. Requires separate APK signing key, KYB/KYC verification, 512x512 icon, 1200x600 banner. Review takes 2-5 business days. On-chain NFTs describe publisher/app/release metadata.
- **React Native scaffold:** Template project with polyfills pre-configured, MWA integration, and basic account reading patterns. Uses AsyncStorage for authorization caching.

**What SMS does NOT provide:**
- Any RPC wrapper, caching layer, or account subscription mechanism
- Any iOS support for MWA (architectural impossibility — iOS suspends background apps, killing the WebSocket channel MWA requires)
- Any custom indexer or data layer
- No pre-built UI components for token balances or account state display

**iOS situation:** MWA is Android-only. iOS alternatives are: (a) embedded wallets via Privy/Particle (best UX), (b) Safari Web Extensions for wallet signing, or (c) deep links (poor UX). Boulder Rollers' Privy choice bypasses this entire problem on both platforms.

**Relevance to Boulder Rollers:** SMS matters primarily for the Solana dApp Store Android distribution channel (grant requirement) and potential Seeker Seed Vault integration. MWA is irrelevant for primary auth since Privy handles it.

## 2. Production dApp Patterns

| App | RPC Method | Caching | Offline | Wallet | Source |
|-----|-----------|---------|---------|--------|--------|
| **Phantom** | Custom infra (SimpleHash). Distributes balance requests across multiple endpoints. Staggers requests. | Closed-source; likely in-memory + backend aggregation | Shows stale balances on disruption | Native wallet; provides Connect SDK | Closed-source |
| **Jupiter** | Self-hosted API with Yellowstone gRPC or poll mode. Swap API: quote → build tx → sign → send. | Backend-side; client polls quote API | Not applicable (swap requires connectivity) | Standard wallet adapters | Open API docs |
| **Tensor** | Helius DAS API for NFT metadata/floor prices. Custom indexer for listing state. | Backend aggregation layer | Closed-source | Standard wallet adapters | Closed-source |
| **Marinade** | TypeScript SDK wrapping on-chain staking program. Standard `Connection` for stake account reads. | Closed-source; no published mobile patterns | Web app; no offline mode | Standard wallet adapters | Open-source program + SDK |
| **Backpack** | Open-source React Native wallet. Uses `@solana/web3.js` with `secure-background` package. | In-memory; no published persistent cache | Shows last-known state | Native wallet + xNFT runtime | Open source |

**Key pattern:** No production Solana mobile app publishes a detailed architecture for on-chain reads + caching. The universal pattern is: backend API aggregates chain state, mobile client reads from that API, with direct RPC calls reserved for verification or transaction building. This aligns with Boulder Rollers' verify-chip approach.

## 3. @solana/web3.js in React Native

**v1 (current):** Required polyfills for Expo SDK 52:
- `react-native-get-random-values` (or `expo-crypto` for SDK 49+)
- `buffer` global — must be imported at entrypoint before web3.js
- Import order matters: `react-native-get-random-values` MUST come before `@solana/web3.js`

**Gap found:** Boulder Rollers does NOT currently have `buffer` in `package.json`. Verify if `expo-crypto` covers it or add explicitly.

**v2 / @solana/kit:** Tree-shakeable, zero dependencies, 10x faster crypto, smaller bundle. BUT requires `SubtleCrypto` API which React Native does not provide. Polyfill chain (`react-native-quick-crypto` + `@solana/webcrypto-ed25519-polyfill`) has known import-order issues. **Stay on v1 for Phase A.** Revisit v2 when polyfill story stabilizes.

**Skipping @coral-xyz/anchor — CORRECT.** Anchor's client pulls Node.js-isms that fight Metro. For read-only deserialization use `anchor-client-gen` (by kklas) — generates standalone TypeScript with `@coral-xyz/borsh` as the only dependency, no full Anchor client.

**Connection lifecycle:** Singleton, created once at startup. No need to recreate per-screen.

## 4. RPC Caching + Offline

- **Stale-while-revalidate:** TanStack React Query with 5-15min staleTime for chain data. Manual `refetchQueries` on verify-chip tap rather than automatic intervals.
- **SQLite persistent cache:** `chain_cache` table with `account_address`, `data_blob`, `slot`, `fetched_at`, `decoded_json`. Show cached values instantly on app open, verify via RPC in background. Strictly better than AsyncStorage for structured account data.
- **Batching:** `getMultipleAccounts` — single RPC call for all PDAs. Max 100 accounts per call. For verify chip (Vault + VaultStake + LocalLegend + ProgramConfig) = 4 accounts in one round trip. Mobile latency to Helius: ~140-225ms.
- **NO websocket subscriptions on mobile.** `accountSubscribe` has 10-minute inactivity timeout, iOS kills background sockets, messages drop under load. Tap-to-verify avoids all of this.
- **Divergence detection:** Include `slot` in both indexer API responses and RPC reads. Only show `diverged` if values differ AND slot delta exceeds threshold (e.g., 10 slots). Below that, show `verified` with fresher data.
- **Helius rate limits:** Free = 10 RPS, paid tiers scale. A single verify tap = 1 batched RPC call. Not a concern for read-only verification.

## 5. Wallet + Signing UX

- **Privy vs MWA:** Privy works on both iOS and Android, creates wallets via social login, signs in-app without app-switching. MWA requires switching to external wallet (Android only). For mainstream cyclists, Privy is strictly superior. For crypto-native users wanting Phantom, Privy also supports external wallet connection.
- **Transaction confirmation:** Use `confirmed` commitment (~400ms), not `finalized` (~6s). For read-only verify chip, commitment level is moot — just reading account state.
- **Do NOT use `signatureSubscribe` on mobile** for same reliability reasons as `accountSubscribe`. Poll `getSignatureStatus` at 1-2s intervals for transaction confirmation.

## 6. Recommendations for Boulder Rollers

**Adopt:**
1. `getMultipleAccounts` batching — single RPC call for all PDAs on verify tap
2. SQLite `chain_cache` with `slot` tracking — cached data instant, verify in background
3. `anchor-client-gen` for typed Borsh decoders from IDL — skip full Anchor
4. Singleton `Connection` with Helius endpoint
5. TanStack React Query with 5-15min staleTime, manual refetch on verify tap
6. Slot-aware divergence detection (10+ slot threshold before `diverged`)

**Avoid:**
1. WebSocket subscriptions on mobile — unreliable, iOS kills them
2. `@coral-xyz/anchor` client in RN — Metro conflicts
3. `@solana/kit` (v2) for now — SubtleCrypto polyfill fragile on RN
4. Auto-polling RPC on intervals — wastes rate budget; tap-to-verify is correct
5. MWA as primary auth — Privy covers both platforms

**Verify before building:**
1. `buffer` polyfill properly loaded at entry point
2. `getMultipleAccounts` tested from Expo dev build on actual device over cellular
3. Helius latency from target markets on mobile networks
4. `@coral-xyz/borsh` works in Metro bundler without additional polyfills

## Sources

1. [Solana Mobile Stack Overview](https://docs.solanamobile.com/)
2. [SMS OEM Introduction](https://blog.solanamobile.com/post/introducing-the-solana-mobile-stack-for-oems-and-hardware-manufacturers)
3. [dApp Store Publishing Guide](https://docs.solanamobile.com/dapp-publishing/overview)
4. [dApp Store Submission Requirements](https://docs.solanamobile.com/dapp-publishing/submit)
5. [Solana Mobile dApp Scaffold](https://github.com/solana-mobile/solana-mobile-dapp-scaffold)
6. [iOS Wallet Signing Limitations](https://docs.solanamobile.com/blog/ios-wallet-signing)
7. [Phantom Wallet SDK](https://docs.phantom.com/wallet-sdks-overview)
8. [Jupiter Self-Hosted API](https://station.jup.ag/docs/apis/self-hosted)
9. [Jupiter Ultra Swap API](https://developers.jup.ag/docs/ultra)
10. [Helius DAS API](https://www.helius.dev/docs/das-api)
11. [Marinade Liquid Staking Program](https://github.com/marinade-finance/liquid-staking-program)
12. [Backpack Wallet Source](https://github.com/coral-xyz/backpack)
13. [Solana web3.js Polyfill Guide](https://docs.solanamobile.com/react-native/polyfill-guides/web3-js)
14. [Solana web3.js v2 Release](https://www.anza.xyz/blog/solana-web3-js-2-release-candidate)
15. [@solana/webcrypto-ed25519-polyfill](https://www.npmjs.com/package/@solana/webcrypto-ed25519-polyfill)
16. [anchor-client-gen](https://github.com/kklas/anchor-client-gen)
17. [Expo dApp Setup Guide](https://docs.solanamobile.com/react-native/expo)
18. [Making RPC Requests from RN](https://docs.solanamobile.com/react-native/making_rpc_requests)
19. [TanStack React Query Caching](https://tanstack.com/query/v4/docs/framework/react/guides/caching)
20. [Offline-First Frontend Patterns 2025](https://blog.logrocket.com/offline-first-frontend-apps-2025-indexeddb-sqlite/)
21. [Helius getMultipleAccounts Guide](https://www.helius.dev/docs/rpc/guides/getmultipleaccounts)
22. [Helius RPC FAQ / Rate Limits](https://www.helius.dev/docs/faqs/rpc)
23. [Solana WebSocket Reliability / Blazar](https://blog.quicknode.com/blazar-solana-websocket-engine/)
24. [Privy Expo Solana Wallets](https://docs.privy.io/guide/expo/embedded/solana/usage)
25. [Solana Transaction Confirmation Guide](https://solana.com/developers/guides/advanced/confirmation)
