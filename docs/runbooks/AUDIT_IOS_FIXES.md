# iOS App Audit - Fix Instructions

## Overview
This document contains all flagged issues from the iOS app audit with detailed fix instructions for each item. Use this to work through fixes systematically.

---

## HIGH PRIORITY FIXES

### 1. GPX/FIT File Parsing Not Implemented
**File:** `ios/BoulderRollers/Services/APIClient.swift:304-317`
**Current State:**
```swift
func uploadRide(fileURL: URL) async throws -> RideUploadResponse {
    // TODO: Parse GPX/FIT file to extract real metrics
    let request = RideUploadRequest(
        rideId: nil,
        tss: 100.0,        // HARDCODED
        kcals: 500.0,      // HARDCODED
        durationSec: 3600, // HARDCODED
        startedAt: Date()  // ALWAYS NOW
    )
    return try await post("/rides/upload", body: request)
}
```

**Solution:**
1. Add a `RideFileParser` service that can handle:
   - `.fit` files (use FIT SDK or parse binary format)
   - `.gpx` files (XML parsing)
   - `.tcx` files (XML parsing)
2. Extract from files:
   - `startedAt` - timestamp from first trackpoint
   - `durationSec` - time between first and last trackpoint
   - `kcals` - from file if available, or calculate from power/HR
   - `tss` - calculate from normalized power and FTP (need user's FTP from profile)
   - `distanceMeters` - sum of trackpoint distances
   - `elevationGain` - sum of positive elevation changes

**Libraries to Consider:**
- `FitDataProtocol` Swift package for FIT files
- Native `XMLParser` for GPX/TCX

**Test Files:** User should have sample .fit/.gpx files to test with

---

### 2. STAKE DUNG Button No-Op
**File:** `ios/BoulderRollers/Views/Map/MapView.swift:248-254`
**Current State:**
```swift
Button {
    // TODO: hook staking flow
} label: {
    Text("STAKE DUNG")
}
```

**Solution:**
1. Create `StakingView.swift` or `StakingSheet.swift`
2. UI should include:
   - Amount input field (DUNG to stake)
   - Current DUNG balance display
   - Segment info summary
   - Estimated LP tokens to receive
   - Confirm button
3. On confirm, call `APIClient.shared.stake(segmentId:amount:)`
4. Show transaction result (success/failure)
5. Present as sheet from segment detail

**Implementation:**
```swift
@State private var showStakingSheet = false
@State private var stakingSegment: APIClient.Segment?

Button {
    stakingSegment = segment
    showStakingSheet = true
} label: {
    Text("STAKE DUNG")
}
.sheet(isPresented: $showStakingSheet) {
    if let segment = stakingSegment {
        StakingSheet(segment: segment)
    }
}
```

---

### 3. RIDE THIS SEGMENT Button No-Op
**File:** `ios/BoulderRollers/Views/Map/MapView.swift:255-261`
**Current State:**
```swift
Button {
    // TODO: hook ride recording
} label: {
    Text("RIDE THIS SEGMENT")
}
```

**Solution:**
1. Create `RideRecordingView.swift` for live ride tracking
2. Features needed:
   - Start/stop recording
   - Live GPS tracking
   - Timer display
   - Distance counter
   - Export to GPX/FIT when done
3. For MVP, can simply:
   - Navigate to RideUploadView with segment context
   - Or show "Coming Soon" alert

**Quick MVP Fix:**
```swift
@State private var showRideComingSoon = false

Button {
    showRideComingSoon = true
} label: {
    Text("RIDE THIS SEGMENT")
}
.alert("Coming Soon", isPresented: $showRideComingSoon) {
    Button("OK", role: .cancel) {}
} message: {
    Text("Live ride recording will be available in a future update. For now, upload a ride file from your cycling computer.")
}
```

---

### 4. Hardcoded Ride Metrics
**File:** `ios/BoulderRollers/Services/APIClient.swift:308-314`
**Same as #1** - Fix by implementing actual file parsing

---

## MEDIUM PRIORITY FIXES

### 5. Silent Error Handling in EditProfileView
**File:** `ios/BoulderRollers/Views/Profile/EditProfileView.swift:176`
**Current State:**
```swift
catch { // Error is handled in viewModel }
```

**Solution:**
Add proper error feedback to user:
```swift
@State private var errorMessage: String?
@State private var showError = false

catch {
    errorMessage = error.localizedDescription
    showError = true
}

.alert("Save Failed", isPresented: $showError) {
    Button("OK", role: .cancel) {}
} message: {
    Text(errorMessage ?? "Unknown error")
}
```

---

### 6. Silent Error Handling in FitnessSettingsView
**File:** `ios/BoulderRollers/Views/Profile/FitnessSettingsView.swift:217`
**Same pattern as #5** - Add alert for error feedback

---

### 7. FTP Info Button Empty
**File:** `ios/BoulderRollers/Views/Profile/FitnessSettingsView.swift:130`
**Current State:**
```swift
Button {
    // Show FTP info
} label: { Image(systemName: "info.circle") }
```

**Solution:**
```swift
@State private var showFTPInfo = false

Button {
    showFTPInfo = true
} label: {
    Image(systemName: "info.circle")
}
.alert("What is FTP?", isPresented: $showFTPInfo) {
    Button("OK", role: .cancel) {}
} message: {
    Text("Functional Threshold Power (FTP) is the maximum power you can sustain for approximately one hour. It's used to calculate Training Stress Score (TSS) and personalize your training zones. You can estimate it from a 20-minute all-out effort (multiply average power by 0.95).")
}
```

---

### 8. BIP39 Import Not Supported
**File:** `ios/BoulderRollers/Services/WalletManager.swift:22`
**Current State:** Only accepts base58 secret keys

**Solution:**
1. Add BIP39 mnemonic parsing
2. Use `swift-bip39` or similar package
3. Derive Solana keypair from seed phrase
4. Update `importWallet()` to detect format:
   - 12/24 words = BIP39 mnemonic
   - Base58 string = secret key

**Note:** This is a nice-to-have, not blocking core functionality

---

### 9. Mapbox Fallback Placeholder
**File:** `ios/BoulderRollers/Views/Map/MapView.swift:47-81`
**Current State:** Shows "Map unavailable" when token missing

**Solution Options:**
1. Use Apple Maps as fallback (MapKit)
2. Show static map image
3. Better error message with setup instructions

**Quick fix - better messaging:**
```swift
private func placeholder(text: String) -> some View {
    Color.black.opacity(0.05)
        .overlay(
            VStack(spacing: 16) {
                Image(systemName: "map")
                    .font(.system(size: 48))
                    .foregroundColor(Colors.grey500)
                Text("Map Setup Required")
                    .font(Typography.h3)
                Text("Add your Mapbox access token to Info.plist to enable the interactive map.")
                    .font(Typography.bodySmall)
                    .multilineTextAlignment(.center)
                Link("Get a free token at mapbox.com", destination: URL(string: "https://mapbox.com")!)
                    .font(Typography.bodySmall)
            }
            .padding()
        )
}
```

---

## LOW PRIORITY (Cleanup)

### 10. Remove Debug Print Statements
**Files:**
- `ios/BoulderRollers/BoulderRollersApp.swift:12` - Remove "ANTIGRAVITY" print
- `ios/BoulderRollers/Services/APIClient.swift:370-424` - Replace with os_log or remove
- `ios/BoulderRollers/Views/CAL/CALView.swift:176` - Remove tx signature print
- `ios/BoulderRollers/Views/Profile/SessionsView.swift:186` - Remove session count print
- `ios/BoulderRollers/Views/Rides/RideUploadView.swift:156` - Remove error detail print

**Solution:**
Either remove entirely or replace with proper logging:
```swift
import os.log

private let logger = Logger(subsystem: "com.boulderrollers.app", category: "API")
logger.debug("API response: \(response)")
```

---

### 11. Remove Commented Shadow Code
**Files:** Multiple UI files have commented `.shadow()` modifiers
- Search for `// .shadow` and either uncomment or remove entirely
- Decide on consistent shadow style across app

---

## Testing Checklist
After implementing fixes:
- [ ] Profile save shows error alert on failure
- [ ] FTP info button shows explanation
- [ ] Ride upload extracts real metrics from file (if parser implemented)
- [ ] Staking flow works end-to-end
- [ ] No debug prints in Xcode console
- [ ] Build succeeds with no warnings
