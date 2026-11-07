# Worker 3: iOS App Engineer

**Context:** Read `BOULDER_ROLLERS_V1_SPEC.md` first for full game design.

**Your Responsibility:** Build the iOS app (wallet, map, ride upload, profile, beetle cards).

**Tech Stack:**
- Swift 5.9+
- SwiftUI (iOS 17+)
- Mapbox SDK
- Solana.swift
- Async/Await + Combine

**Working Directory:** `/ios/`

---

## Current State (Starting Fresh)

No iOS app exists yet. You're building from scratch.

---

## Your 7-Week Plan

### Week 1: Project Setup & Wallet

#### Task 3.1: Create Xcode Project (Day 1)

```bash
# From repo root
cd /Users/gabetemp/curahee/BoulderRollers-v2
mkdir ios
cd ios

# Create new Xcode project:
# - iOS App
# - SwiftUI
# - Minimum iOS 17.0
# - Product Name: BoulderRollers
# - Bundle ID: com.boulderrollers.app
```

**Project Structure:**
```
BoulderRollers/
├── BoulderRollersApp.swift
├── Views/
│   ├── Onboarding/
│   ├── Map/
│   ├── Profile/
│   ├── Segments/
│   └── Rides/
├── ViewModels/
├── Models/
├── Services/
│   ├── WalletManager.swift
│   ├── APIClient.swift
│   ├── SolanaClient.swift
│   └── LocationManager.swift
├── Utilities/
│   ├── DesignSystem.swift
│   └── Extensions.swift
└── Resources/
    └── Assets.xcassets
```

---

#### Task 3.2: Add Dependencies (Day 1)

**Add via Swift Package Manager:**
```swift
// In Xcode: File > Add Package Dependencies

// 1. Solana.swift
https://github.com/solana-mobile/Solana.Swift
// Version: 1.0+

// 2. Mapbox Maps SDK
https://github.com/mapbox/mapbox-maps-ios
// Version: 10.0+

// 3. Kingfisher (image caching)
https://github.com/onevcat/Kingfisher
// Version: 7.0+
```

**Configure Info.plist:**
```xml
<key>NSLocationWhenInUseUsageDescription</key>
<string>Boulder Rollers needs your location to show nearby segments and record rides.</string>

<key>NSLocationAlwaysAndWhenInUseUsageDescription</key>
<string>Boulder Rollers needs your location to record rides in the background.</string>

<key>UIBackgroundModes</key>
<array>
    <string>location</string>
</array>

<key>MBXAccessToken</key>
<string>YOUR_MAPBOX_TOKEN_HERE</string>
```

---

#### Task 3.3: Design System (Day 2)

**Create `Utilities/DesignSystem.swift`:**
```swift
import SwiftUI

enum Colors {
    static let voidBlack = Color(hex: "111111")
    static let internationalOrange = Color(hex: "FF4400")
    static let brushedAluminum = Color(hex: "E0E0E0")
    static let stucco = Color(hex: "F4F4F0")
}

enum Typography {
    static let monospace = Font.custom("Menlo", size: 16)
    static let monospaceBold = Font.custom("Menlo-Bold", size: 16)
    static let body = Font.system(size: 16, design: .default)
    static let title = Font.system(size: 24, weight: .bold, design: .default)
}

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
        var int: UInt64 = 0
        Scanner(string: hex).scanHexInt64(&int)
        let a, r, g, b: UInt64
        switch hex.count {
        case 6: // RGB
            (a, r, g, b) = (255, int >> 16, int >> 8 & 0xFF, int & 0xFF)
        case 8: // ARGB
            (a, r, g, b) = (int >> 24, int >> 16 & 0xFF, int >> 8 & 0xFF, int & 0xFF)
        default:
            (a, r, g, b) = (255, 0, 0, 0)
        }

        self.init(
            .sRGB,
            red: Double(r) / 255,
            green: Double(g) / 255,
            blue:  Double(b) / 255,
            opacity: Double(a) / 255
        )
    }
}

// Reusable components
struct PrimaryButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(Typography.monospaceBold)
                .foregroundColor(Colors.stucco)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Colors.voidBlack)
                .cornerRadius(8)
        }
    }
}

struct OrangeAccentButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(Typography.monospaceBold)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Colors.internationalOrange)
                .cornerRadius(8)
        }
    }
}
```

---

#### Task 3.4: Wallet Manager (Day 3-4)

**Create `Services/WalletManager.swift`:**
```swift
import Foundation
import Solana
import CryptoKit
import Security

@MainActor
class WalletManager: ObservableObject {
    @Published var isConnected = false
    @Published var publicKey: String?

    private let keychainService = "com.boulderrollers.wallet"
    private let keychainAccount = "solana_keypair"

    // Generate new wallet
    func createWallet() async throws {
        let account = try Account(network: .mainnetBeta)

        // Store in Keychain
        try storeKeypair(account)

        self.publicKey = account.publicKey.base58EncodedString
        self.isConnected = true
    }

    // Import wallet from seed phrase
    func importWallet(seedPhrase: String) async throws {
        // Parse seed phrase to derive keypair
        // (Use BIP39 implementation)

        // TODO: Implement seed phrase derivation
        throw NSError(domain: "NotImplemented", code: -1)
    }

    // Load existing wallet from Keychain
    func loadWallet() async throws {
        guard let keypairData = try loadKeypairFromKeychain() else {
            throw WalletError.noWalletFound
        }

        let account = try Account(data: keypairData, network: .mainnetBeta)
        self.publicKey = account.publicKey.base58EncodedString
        self.isConnected = true
    }

    // Sign message
    func signMessage(_ message: String) async throws -> String {
        guard let keypairData = try loadKeypairFromKeychain() else {
            throw WalletError.noWalletFound
        }

        let account = try Account(data: keypairData, network: .mainnetBeta)
        let messageData = message.data(using: .utf8)!
        let signature = try account.sign(messageData)

        return signature.base58EncodedString
    }

    // Keychain helpers
    private func storeKeypair(_ account: Account) throws {
        // Serialize keypair
        let keypairData = account.secretKey

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
            kSecValueData as String: keypairData
        ]

        // Delete existing first
        SecItemDelete(query as CFDictionary)

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw WalletError.keychainError
        }
    }

    private func loadKeypairFromKeychain() throws -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: keychainAccount,
            kSecReturnData as String: true
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        if status == errSecSuccess {
            return result as? Data
        } else if status == errSecItemNotFound {
            return nil
        } else {
            throw WalletError.keychainError
        }
    }
}

enum WalletError: LocalizedError {
    case noWalletFound
    case keychainError

    var errorDescription: String? {
        switch self {
        case .noWalletFound:
            return "No wallet found. Please create or import a wallet."
        case .keychainError:
            return "Failed to access Keychain."
        }
    }
}
```

---

#### Task 3.5: Onboarding Flow (Day 5)

**Create `Views/Onboarding/OnboardingView.swift`:**
```swift
import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var walletManager: WalletManager
    @State private var currentPage = 0

    var body: some View {
        TabView(selection: $currentPage) {
            WelcomeView()
                .tag(0)

            CreateWalletView()
                .tag(1)

            LocationPermissionView()
                .tag(2)
        }
        .tabViewStyle(.page(indexDisplayMode: .always))
    }
}

struct WelcomeView: View {
    var body: some View {
        VStack(spacing: 30) {
            Spacer()

            Image(systemName: "map.fill")
                .resizable()
                .frame(width: 100, height: 100)
                .foregroundColor(Colors.internationalOrange)

            Text("BOULDER ROLLERS")
                .font(Typography.title)
                .foregroundColor(Colors.voidBlack)

            Text("Own the map. Earn from the routes you ride.")
                .font(Typography.body)
                .multilineTextAlignment(.center)
                .foregroundColor(Colors.voidBlack)
                .padding(.horizontal, 40)

            Spacer()

            OrangeAccentButton(title: "Get Started") {
                // Advance to next page
            }
            .padding(.horizontal, 40)
        }
        .background(Colors.stucco)
    }
}

struct CreateWalletView: View {
    @EnvironmentObject var walletManager: WalletManager
    @State private var isCreating = false

    var body: some View {
        VStack(spacing: 30) {
            Text("Create Wallet")
                .font(Typography.title)

            Text("Your wallet is your identity on Solana. Keep it secure.")
                .font(Typography.body)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Spacer()

            PrimaryButton(title: "Create New Wallet") {
                Task {
                    isCreating = true
                    try await walletManager.createWallet()
                    isCreating = false
                }
            }
            .padding(.horizontal, 40)
            .disabled(isCreating)

            Button("Import Existing Wallet") {
                // Show import sheet
            }
            .foregroundColor(Colors.internationalOrange)
        }
        .background(Colors.stucco)
    }
}

struct LocationPermissionView: View {
    @StateObject private var locationManager = LocationManager()

    var body: some View {
        VStack(spacing: 30) {
            Text("Enable Location")
                .font(Typography.title)

            Text("We need your location to show nearby segments and record rides.")
                .font(Typography.body)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Spacer()

            OrangeAccentButton(title: "Enable Location") {
                locationManager.requestPermission()
            }
            .padding(.horizontal, 40)

            Button("Skip for now") {
                // Continue anyway
            }
            .foregroundColor(Colors.voidBlack)
        }
        .background(Colors.stucco)
    }
}
```

**Deliverable:** Onboarding complete, wallet created, location permission requested

---

### Week 2: Authentication & Profile

#### Task 3.6: API Client (Day 1-2)

**Create `Services/APIClient.swift`:**
```swift
import Foundation

class APIClient {
    static let shared = APIClient()

    private let baseURL: String
    private var jwtToken: String?

    init() {
        #if DEBUG
        baseURL = "https://dev-api.boulderrollers.com"
        #else
        baseURL = "https://api.boulderrollers.com"
        #endif
    }

    func setAuthToken(_ token: String) {
        self.jwtToken = token
        // Store in Keychain
        storeTokenInKeychain(token)
    }

    func getAuthToken() -> String? {
        if let token = jwtToken {
            return token
        }
        // Load from Keychain
        return loadTokenFromKeychain()
    }

    // MARK: - Auth

    struct WalletAuthRequest: Codable {
        let pubkey: String
        let signature: String
        let message: String
    }

    struct AuthResponse: Codable {
        let jwt: String
        let user_id: Int64
        let pubkey: String
    }

    func authenticateWallet(pubkey: String, signature: String, message: String) async throws -> AuthResponse {
        let request = WalletAuthRequest(pubkey: pubkey, signature: signature, message: message)
        return try await post("/api/v1/auth/wallet", body: request)
    }

    // MARK: - Users

    struct UserProfile: Codable {
        let id: Int64
        let pubkey: String
        let username: String?
        let email: String?
        let total_rides: Int64
        let total_tss: Int64
    }

    func getCurrentUser() async throws -> UserProfile {
        return try await get("/api/v1/users/me")
    }

    // MARK: - Segments

    struct Segment: Codable, Identifiable {
        let id: Int64
        let creator_pubkey: String
        let start_lat: Double
        let start_lon: Double
        let end_lat: Double
        let end_lon: Double
        let distance_meters: Int
        let elevation_gain: Int
        let name: String
        let description: String?
        let total_rides: Int64
        let total_staked: Int64
    }

    func getNearbySegments(lat: Double, lon: Double, radiusKm: Double) async throws -> [Segment] {
        struct Response: Codable {
            let segments: [Segment]
        }
        let response: Response = try await get("/api/v1/segments/nearby?lat=\(lat)&lon=\(lon)&radius_km=\(radiusKm)")
        return response.segments
    }

    // MARK: - Generic Request Methods

    private func get<T: Decodable>(_ path: String) async throws -> T {
        var request = URLRequest(url: URL(string: baseURL + path)!)
        request.httpMethod = "GET"

        if let token = getAuthToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.requestFailed
        }

        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Encodable, R: Decodable>(_ path: String, body: T) async throws -> R {
        var request = URLRequest(url: URL(string: baseURL + path)!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = getAuthToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.requestFailed
        }

        return try JSONDecoder().decode(R.self, from: data)
    }

    // Keychain helpers
    private func storeTokenInKeychain(_ token: String) {
        // Similar to WalletManager
    }

    private func loadTokenFromKeychain() -> String? {
        // Similar to WalletManager
        return nil
    }
}

enum APIError: LocalizedError {
    case requestFailed
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .requestFailed:
            return "Request failed"
        case .invalidResponse:
            return "Invalid response from server"
        }
    }
}
```

---

#### Task 3.7: Sign In Flow (Day 3)

**Create `Views/Auth/SignInView.swift`:**
```swift
import SwiftUI

struct SignInView: View {
    @EnvironmentObject var walletManager: WalletManager
    @State private var isSigning = false
    @State private var error: String?

    var body: some View {
        VStack(spacing: 30) {
            Text("Sign In")
                .font(Typography.title)

            if let error = error {
                Text(error)
                    .foregroundColor(.red)
            }

            Spacer()

            OrangeAccentButton(title: "Sign In with Wallet") {
                Task {
                    await signIn()
                }
            }
            .padding(.horizontal, 40)
            .disabled(isSigning)
        }
        .background(Colors.stucco)
    }

    func signIn() async {
        isSigning = true
        error = nil

        do {
            // 1. Create message with timestamp
            let timestamp = Int(Date().timeIntervalSince1970)
            let message = "Sign in to Boulder Rollers: \(timestamp)"

            // 2. Sign message with wallet
            let signature = try await walletManager.signMessage(message)

            guard let pubkey = walletManager.publicKey else {
                throw WalletError.noWalletFound
            }

            // 3. Call API
            let response = try await APIClient.shared.authenticateWallet(
                pubkey: pubkey,
                signature: signature,
                message: message
            )

            // 4. Store JWT
            APIClient.shared.setAuthToken(response.jwt)

            // Navigation handled by App state

        } catch {
            self.error = error.localizedDescription
        }

        isSigning = false
    }
}
```

---

#### Task 3.8: Profile View (Day 4-5)

**Create `Views/Profile/ProfileView.swift`:**
```swift
import SwiftUI

struct ProfileView: View {
    @StateObject private var viewModel = ProfileViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                // Beetle Card (placeholder for now)
                BeetleCardPlaceholder()

                // Stats
                StatsGrid(profile: viewModel.profile)

                // Actions
                Button("Sign Out") {
                    viewModel.signOut()
                }
                .foregroundColor(.red)
            }
            .padding()
        }
        .background(Colors.stucco)
        .task {
            await viewModel.loadProfile()
        }
    }
}

struct BeetleCardPlaceholder: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 16)
                .fill(Colors.brushedAluminum)
                .frame(height: 300)

            VStack {
                Image(systemName: "ladybug.fill")
                    .resizable()
                    .frame(width: 100, height: 100)
                    .foregroundColor(Colors.internationalOrange)

                Text("Rank: B")
                    .font(Typography.monospaceBold)
            }
        }
        .padding(.horizontal)
    }
}

struct StatsGrid: View {
    let profile: APIClient.UserProfile?

    var body: some View {
        if let profile = profile {
            VStack(spacing: 16) {
                HStack(spacing: 16) {
                    StatCard(title: "Rides", value: "\(profile.total_rides)")
                    StatCard(title: "TSS", value: "\(profile.total_tss)")
                }

                HStack(spacing: 16) {
                    StatCard(title: "DUNG", value: "0") // TODO: Get from Solana
                    StatCard(title: "CAL", value: "0") // TODO: Get from Solana
                }
            }
            .padding(.horizontal)
        }
    }
}

struct StatCard: View {
    let title: String
    let value: String

    var body: some View {
        VStack {
            Text(value)
                .font(Typography.title)
                .foregroundColor(Colors.voidBlack)
            Text(title)
                .font(Typography.body)
                .foregroundColor(Colors.voidBlack.opacity(0.6))
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Colors.brushedAluminum)
        .cornerRadius(8)
    }
}

@MainActor
class ProfileViewModel: ObservableObject {
    @Published var profile: APIClient.UserProfile?
    @Published var isLoading = false

    func loadProfile() async {
        isLoading = true

        do {
            profile = try await APIClient.shared.getCurrentUser()
        } catch {
            print("Error loading profile: \(error)")
        }

        isLoading = false
    }

    func signOut() {
        // Clear JWT, reset app state
    }
}
```

**Deliverable:** Sign in works, profile displays user stats

---

### Week 3-4: Map View & Segments

(Due to length constraints, I'll provide key tasks outline)

**Task 3.9:** Integrate Mapbox SDK, show user location

**Task 3.10:** Load and display nearby segments as polylines

**Task 3.11:** Implement segment detail sheet (tap on segment)

**Task 3.12:** Add segment creation flow (draw on map)

**Task 3.13:** Implement segment search (by name)

---

### Week 5: Ride Upload

**Task 3.14:** File picker for GPX/FIT upload

**Task 3.15:** Basic GPS recorder (start/stop)

**Task 3.16:** Upload progress UI

**Task 3.17:** Push notifications (ride processed)

---

### Week 6: Polish

**Task 3.18:** Animations and transitions

**Task 3.19:** Error handling and loading states

**Task 3.20:** Offline mode (cache segments)

---

### Week 7: TestFlight & Launch

**Task 3.21:** Submit to TestFlight

**Task 3.22:** Beta testing and bug fixes

**Task 3.23:** App Store submission

---

## App Entry Point

**Update `BoulderRollersApp.swift`:**
```swift
import SwiftUI

@main
struct BoulderRollersApp: App {
    @StateObject private var walletManager = WalletManager()
    @State private var hasCompletedOnboarding = false

    var body: some Scene {
        WindowGroup {
            if walletManager.isConnected && hasCompletedOnboarding {
                MainTabView()
                    .environmentObject(walletManager)
            } else if walletManager.isConnected {
                SignInView()
                    .environmentObject(walletManager)
            } else {
                OnboardingView()
                    .environmentObject(walletManager)
            }
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            MapView()
                .tabItem {
                    Label("Map", systemImage: "map")
                }

            ProfileView()
                .tabItem {
                    Label("Profile", systemImage: "person")
                }
        }
    }
}
```

---

## Communication with Other Workers

**From Worker 2 (Backend) you need:**
- API base URL (dev + prod)
- API documentation (endpoints, request/response schemas)
- Auth flow (JWT format)

**From Worker 1 (Solana) you need:**
- Program IDs (for transaction signing)
- IDL files (to build transactions)

**Deliverables each week:**
1. TestFlight build (internal testing)
2. Screenshots of new screens
3. Report bugs found (in Slack)

---

## Resources

- SwiftUI Tutorials: https://developer.apple.com/tutorials/swiftui
- Mapbox iOS: https://docs.mapbox.com/ios/maps/
- Solana.swift: https://github.com/solana-mobile/Solana.Swift
- Your working directory: `/ios/`
- Run: Cmd+R in Xcode
