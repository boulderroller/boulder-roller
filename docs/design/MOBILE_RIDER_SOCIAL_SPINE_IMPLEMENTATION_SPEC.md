# Mobile Rider Social Spine Implementation Spec

**Status:** Implementation-ready  
**Date:** 2026-04-24  
**Audience:** Mobile, backend, product, design  
**Scope:** First mobile implementation slice for rider identity as a tappable social object

## 1. Purpose

This spec turns the rider identity/social shape into code.

The goal is not to ship a full social network. The goal is to make `Rider` a first-class mobile object:

- recognizable in rows
- tappable from climb glory surfaces
- inspectable on a public rider detail screen
- owner-mode in Profile
- backed by real backend contracts

## 2. Non-Negotiable Product Line

Boulder Roller social starts from verified riding identity, not generic likes.

This slice must not add:
- fake comments
- fake kudos
- fake follower counts
- fake recent rides
- fake public BeetleCards
- wallet-first identity
- proof/protocol copy on rider surfaces

## 3. Current Backend Contracts

### 3.1 Available Now

These contracts are real enough to wire:

- `GET /users/me`
  - owner profile
  - username, display name, avatar, bio, public/private flag
  - total rides, distance, elevation, TSS, duration

- `GET /users/{identifier}`
  - public profile by wallet or username
  - private profiles return minimal public-safe data

- `POST /social/follow/{user_id}`
- `DELETE /social/follow/{user_id}`
- `GET /social/is-following/{user_id}`
  - backend-owned follow state

- `GET /users/me/leaderboard-positions`
- `GET /users/{wallet}/leaderboard-positions`
  - authenticated cross-climb glory summary

- `GET /beetles/my-cards`
  - owner-only BeetleCard list

### 3.2 Not Available Yet

Do not fake these:

- public BeetleCards for another rider
- public recent rides for another rider
- profile media
- comments
- kudos/reactions
- feed ranking
- follower/following counts on profile

File backend follow-up beads when these become product priorities.

## 4. Mobile Object Model

### 4.1 `RiderIdentity`

Fields:
- `id?`
- `wallet?`
- `username?`
- `displayName?`
- `avatarUrl?`
- `isPublic?`

Label priority:

1. `displayName`
2. `@username`
3. `Rider abcd...wxyz`
4. `Rider`

Rules:
- never uppercase handles
- never use `You` as an author/rider row label
- short wallet is fallback/account context only

### 4.2 `RiderDetail`

Fields:
- identity
- public profile stats
- follow state when authenticated
- leaderboard summary when available

### 4.3 `BeetleCardSummary`

Fields:
- card type
- scope name
- score
- level
- patterns scored

Owner:
- Profile owner-mode only until public rider BeetleCard endpoint exists.

## 5. Components

### 5.1 `RiderHeader`

Purpose:
- one identity block for Profile and RiderDetail

Contains:
- avatar/initial
- primary rider label
- secondary handle/account line
- optional bio
- optional action slot

Rules:
- identity first
- wallet secondary
- no protocol nouns

### 5.2 `RiderRow`

Purpose:
- compact tappable rider row for leaderboard and legend surfaces

Contains:
- optional rank
- avatar/initial
- rider label
- optional subtitle
- optional value

Rules:
- tap opens `RiderDetail`
- row can render wallet fallback while profile lookup is pending
- do not show raw wallet as primary if username/display name is known

### 5.3 `FollowButton`

Purpose:
- backend-owned follow action

States:
- `loading`
- `following`
- `not_following`
- `mutual`
- `self`
- `error`

Rules:
- only show enabled follow actions after `is-following` resolves
- self state is not an action
- no optimistic fake follower counts

### 5.4 `BeetleCardModule`

Purpose:
- owner-mode Profile module for visible effort identity

Rules:
- use `/beetles/my-cards`
- show score/level/pattern count only
- omit if endpoint is unavailable
- do not present upgrade costs or token mechanics here

## 6. Entry Points

### 6.1 Profile

Profile becomes owner-mode Rider Detail.

Ordering:

1. top tab header
2. `RiderHeader`
3. rider stats
4. BeetleCard module if cards load
5. top climbs / glory summary if positions load
6. settings grouped section

### 6.2 Climb Detail

Use `RiderRow` for:
- top-times preview rows
- current Legend holder

Rows tap to `RiderDetail`.

### 6.3 Climb Leaderboard

Use `RiderRow` for:
- KOM summary
- Top 10 rows

Rows tap to `RiderDetail`.

### 6.4 Rider Detail

Route:
- `RiderDetail`

Params:
- `identifier`: wallet or username
- optional initial rider identity for instant fallback
- optional stable `backLabel`

Modules:

1. rider identity
2. rider stats
3. top climbs when leaderboard summary loads
4. unavailable/private state when profile is private or missing

## 7. Deferrals

Backend follow-ups before mobile should expose these:

- public BeetleCard endpoint by user id/wallet
- public rider recent rides contract with privacy controls
- follower/following counts
- feed author enrichment in ride feed
- privacy-aware comments/kudos

## 8. Acceptance Criteria

The spine is aligned when:

1. A rider can be tapped from leaderboard/legend surfaces into `RiderDetail`.
2. Profile and RiderDetail share rider identity primitives.
3. Profile uses real owner BeetleCards when present.
4. No rider surface uses wallet as primary identity when profile identity exists.
5. Follow/unfollow only appears when backed by backend state.
6. Tests lock identity fallback and rider-copy boundaries.
