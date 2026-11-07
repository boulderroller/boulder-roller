# Worker C: iOS Features

> **Priority:** P3
> **Estimated Scope:** 4 tasks
> **Dependencies:** Backend social endpoints (Worker B) for full integration
> **Branch:** `feat/ios-achievements-ui`

---

## Overview

Implement missing iOS features: Achievements UI, enhanced DUNG celebration, and ride history improvements. Backend endpoints already exist for most features.

---

## Tasks

### IOS-301: Achievements View

**Current:** Backend has 8 achievement types, iOS shows nothing
**API Available:** `GET /users/me/achievements`

**Achievement Types:**
- `kom` - King of Mountain
- `pr` - Personal Record
- `podium` - Top 3 finish
- `power_record` - New max power
- `distance_milestone` - 100km, 500km, 1000km...
- `elevation_milestone` - 1000m, 5000m, 10000m...
- `first_ride` - Welcome badge
- `streak` - Consecutive ride days

**Implementation:**

```swift
// ios/BoulderRollers/Models/Achievement.swift
import Foundation

struct Achievement: Codable, Identifiable {
    let id: String
    let achievementType: String
    let title: String
    let description: String?
    let value: Double?
    let rank: Int?
    let createdAt: Date?

    var icon: String {
        switch achievementType {
        case "kom": return "crown.fill"
        case "pr": return "star.fill"
        case "podium": return "medal.fill"
        case "power_record": return "bolt.fill"
        case "distance_milestone": return "figure.outdoor.cycle"
        case "elevation_milestone": return "mountain.2.fill"
        case "first_ride": return "bicycle"
        case "streak": return "flame.fill"
        default: return "trophy.fill"
        }
    }

    var color: Color {
        switch achievementType {
        case "kom": return .yellow
        case "pr": return .orange
        case "podium": return .purple
        case "power_record": return .red
        case "distance_milestone": return .blue
        case "elevation_milestone": return .green
        case "first_ride": return .teal
        case "streak": return .orange
        default: return .gray
        }
    }
}
```

```swift
// ios/BoulderRollers/Views/Profile/AchievementsView.swift
import SwiftUI

struct AchievementsView: View {
    @State private var achievements: [Achievement] = []
    @State private var isLoading = true
    @State private var error: String?

    let columns = [
        GridItem(.flexible()),
        GridItem(.flexible()),
        GridItem(.flexible())
    ]

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.lg) {
                headerSection

                if isLoading {
                    ProgressView()
                        .padding(.top, Spacing.xl)
                } else if let error = error {
                    errorSection(error)
                } else if achievements.isEmpty {
                    emptySection
                } else {
                    achievementsGrid
                }
            }
            .padding()
        }
        .background(Colors.stucco)
        .task {
            await loadAchievements()
        }
    }

    private var headerSection: some View {
        VStack(spacing: Spacing.sm) {
            Text("ACHIEVEMENTS")
                .font(Typography.h1)
            Text("\(achievements.count) unlocked")
                .font(Typography.body)
                .foregroundColor(Colors.grey700)
        }
    }

    private var achievementsGrid: some View {
        LazyVGrid(columns: columns, spacing: Spacing.md) {
            ForEach(achievements) { achievement in
                AchievementCard(achievement: achievement)
            }
        }
    }

    private var emptySection: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "trophy")
                .font(.system(size: 64))
                .foregroundColor(Colors.grey400)

            Text("No achievements yet")
                .font(Typography.h3)

            Text("Complete rides to unlock achievements!")
                .font(Typography.body)
                .foregroundColor(Colors.grey700)
                .multilineTextAlignment(.center)
        }
        .padding(.top, Spacing.xl)
    }

    private func errorSection(_ error: String) -> some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 48))
                .foregroundColor(Colors.error)

            Text(error)
                .font(Typography.body)
                .foregroundColor(Colors.error)

            Button("Retry") {
                Task { await loadAchievements() }
            }
            .neoButton(gradient: Gradients.blueCyan)
        }
    }

    private func loadAchievements() async {
        isLoading = true
        error = nil

        do {
            achievements = try await APIClient.shared.getAchievements()
            // Sort by date, most recent first
            achievements.sort { ($0.createdAt ?? .distantPast) > ($1.createdAt ?? .distantPast) }
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}

struct AchievementCard: View {
    let achievement: Achievement
    @State private var isAnimating = false

    var body: some View {
        VStack(spacing: Spacing.sm) {
            ZStack {
                Circle()
                    .fill(achievement.color.opacity(0.2))
                    .frame(width: 60, height: 60)

                Image(systemName: achievement.icon)
                    .font(.system(size: 28))
                    .foregroundColor(achievement.color)
                    .scaleEffect(isAnimating ? 1.1 : 1.0)
            }

            Text(achievement.title)
                .font(Typography.monoSmall)
                .foregroundColor(Colors.black)
                .multilineTextAlignment(.center)
                .lineLimit(2)

            if let value = achievement.value {
                Text(formatValue(value, type: achievement.achievementType))
                    .font(Typography.monoSmall)
                    .foregroundColor(Colors.grey500)
            }
        }
        .padding(Spacing.sm)
        .frame(maxWidth: .infinity)
        .neoCard()
        .onAppear {
            withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                isAnimating = true
            }
        }
    }

    private func formatValue(_ value: Double, type: String) -> String {
        switch type {
        case "kom", "pr":
            let minutes = Int(value) / 60
            let seconds = Int(value) % 60
            return "\(minutes):\(String(format: "%02d", seconds))"
        case "distance_milestone":
            return "\(Int(value / 1000)) km"
        case "elevation_milestone":
            return "\(Int(value)) m"
        case "power_record":
            return "\(Int(value)) W"
        case "streak":
            return "\(Int(value)) days"
        default:
            return ""
        }
    }
}
```

**Add to ProfileView:**
```swift
// In ProfileView.swift, add navigation to achievements
NavigationLink(destination: AchievementsView()) {
    HStack {
        Image(systemName: "trophy.fill")
            .foregroundColor(Colors.orange)
        Text("Achievements")
        Spacer()
        Text("\(achievementCount)")
            .foregroundColor(Colors.grey500)
        Image(systemName: "chevron.right")
            .foregroundColor(Colors.grey400)
    }
    .padding()
    .neoCard()
}
```

---

### IOS-302: Enhanced DUNG Celebration

**Current:** DUNG amount shown but not prominent

**Implementation:**

```swift
// ios/BoulderRollers/Views/Rides/DungCelebrationView.swift
import SwiftUI
import ConfettiSwiftUI

struct DungCelebrationView: View {
    let dungEarned: Int
    let metrics: RideMetricsData
    let onDismiss: () -> Void

    @State private var confettiCounter = 0
    @State private var showDung = false
    @State private var dungScale: CGFloat = 0.1
    @State private var showMetrics = false

    var body: some View {
        ZStack {
            // Background
            Colors.stucco.ignoresSafeArea()

            VStack(spacing: Spacing.xl) {
                Spacer()

                // DUNG earned - main attraction
                if showDung {
                    VStack(spacing: Spacing.md) {
                        Text("🪲")
                            .font(.system(size: 80))
                            .scaleEffect(dungScale)

                        Text("+\(dungEarned)")
                            .font(.system(size: 72, weight: .bold, design: .rounded))
                            .foregroundColor(Colors.orange)
                            .scaleEffect(dungScale)

                        Text("DUNG EARNED")
                            .font(Typography.h2)
                            .foregroundColor(Colors.grey700)
                    }
                    .transition(.scale.combined(with: .opacity))
                }

                // Metrics summary
                if showMetrics {
                    metricsCard
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                Spacer()

                // Buttons
                if showMetrics {
                    VStack(spacing: Spacing.md) {
                        Button {
                            shareToTwitter()
                        } label: {
                            HStack {
                                Image(systemName: "square.and.arrow.up")
                                Text("SHARE")
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .neoButton(gradient: Gradients.blueCyan)

                        Button {
                            onDismiss()
                        } label: {
                            Text("DONE")
                                .frame(maxWidth: .infinity)
                        }
                        .neoButton(gradient: Gradients.orangeYellow)
                    }
                    .padding(.horizontal)
                    .transition(.opacity)
                }
            }
            .padding()

            // Confetti overlay
            ConfettiCannon(
                counter: $confettiCounter,
                num: 50,
                colors: [.orange, .yellow, .green, .blue],
                confettiSize: 10,
                rainHeight: 800,
                radius: 400
            )
        }
        .onAppear {
            startAnimation()
        }
    }

    private var metricsCard: some View {
        VStack(spacing: Spacing.md) {
            HStack {
                metricItem(
                    value: formatDuration(metrics.durationSec ?? 0),
                    label: "Duration",
                    icon: "clock"
                )
                Spacer()
                metricItem(
                    value: formatDistance(metrics.distanceM ?? 0),
                    label: "Distance",
                    icon: "point.topleft.down.curvedto.point.bottomright.up"
                )
                Spacer()
                metricItem(
                    value: formatElevation(metrics.elevationGainM ?? 0),
                    label: "Elevation",
                    icon: "mountain.2"
                )
            }

            Divider()

            HStack {
                metricItem(
                    value: String(format: "%.0f", metrics.tss ?? 0),
                    label: "TSS",
                    icon: "flame"
                )
                Spacer()
                metricItem(
                    value: String(format: "%.0f", metrics.kcals ?? 0),
                    label: "Calories",
                    icon: "bolt"
                )
                Spacer()
                if let np = metrics.normalizedPowerW {
                    metricItem(
                        value: String(format: "%.0f W", np),
                        label: "NP",
                        icon: "waveform.path.ecg"
                    )
                } else {
                    metricItem(value: "-", label: "NP", icon: "waveform.path.ecg")
                }
            }
        }
        .padding()
        .neoCard()
    }

    private func metricItem(value: String, label: String, icon: String) -> some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundColor(Colors.grey500)
            Text(value)
                .font(Typography.h3)
            Text(label)
                .font(Typography.monoSmall)
                .foregroundColor(Colors.grey500)
        }
    }

    private func startAnimation() {
        // Fire confetti immediately
        confettiCounter += 1

        // Show DUNG with scale animation
        withAnimation(.spring(response: 0.6, dampingFraction: 0.6)) {
            showDung = true
            dungScale = 1.0
        }

        // Haptic feedback
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)

        // Show metrics after delay
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            withAnimation(.easeOut(duration: 0.5)) {
                showMetrics = true
            }
        }

        // Second confetti burst
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            confettiCounter += 1
        }
    }

    private func shareToTwitter() {
        let text = "Just earned \(dungEarned) DUNG on @BoulderRollers! 🪲\n\n\(formatDistance(metrics.distanceM ?? 0)) • \(formatElevation(metrics.elevationGainM ?? 0)) elevation • \(Int(metrics.tss ?? 0)) TSS\n\n#CyclingToEarn #Solana"

        if let url = URL(string: "https://twitter.com/intent/tweet?text=\(text.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")") {
            UIApplication.shared.open(url)
        }
    }

    // Formatters...
    private func formatDuration(_ seconds: Int) -> String {
        let hours = seconds / 3600
        let minutes = (seconds % 3600) / 60
        if hours > 0 {
            return "\(hours)h \(minutes)m"
        }
        return "\(minutes)m"
    }

    private func formatDistance(_ meters: Double) -> String {
        let km = meters / 1000
        return String(format: "%.1f km", km)
    }

    private func formatElevation(_ meters: Double) -> String {
        return String(format: "%.0f m", meters)
    }
}
```

**Update RideUploadView to show celebration:**
```swift
// In RideUploadView.swift, update completedSection
private func completedSection(for state: RideProcessingState) -> some View {
    Group {
        if let metrics = state.metrics, let dung = state.dungMinted, dung > 0 {
            DungCelebrationView(
                dungEarned: dung,
                metrics: metrics,
                onDismiss: {
                    appState.clearCompletedRide(rideId: state.rideId)
                }
            )
        } else {
            // Fallback to simple completion view
            simpleCompletedView(for: state)
        }
    }
}
```

**Add ConfettiSwiftUI package:**
```swift
// In Package.swift or via Xcode:
// Add: https://github.com/simibac/ConfettiSwiftUI
```

---

### IOS-303: Rides History Tab

**Current:** Can view recent rides in upload view, but no dedicated history

**Implementation:**

```swift
// ios/BoulderRollers/Views/Rides/RidesHistoryView.swift
import SwiftUI

struct RidesHistoryView: View {
    @State private var rides: [RideSummary] = []
    @State private var isLoading = true
    @State private var error: String?

    var body: some View {
        NavigationView {
            Group {
                if isLoading {
                    ProgressView("Loading rides...")
                } else if let error = error {
                    errorView(error)
                } else if rides.isEmpty {
                    emptyView
                } else {
                    ridesList
                }
            }
            .navigationTitle("Ride History")
            .background(Colors.stucco)
        }
        .task {
            await loadRides()
        }
        .refreshable {
            await loadRides()
        }
    }

    private var ridesList: some View {
        List {
            ForEach(groupedRides.keys.sorted(by: >), id: \.self) { month in
                Section(header: Text(month)) {
                    ForEach(groupedRides[month] ?? []) { ride in
                        NavigationLink(destination: RideDetailView(rideId: ride.id)) {
                            RideRowView(ride: ride)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private var groupedRides: [String: [RideSummary]] {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMMM yyyy"

        return Dictionary(grouping: rides) { ride in
            formatter.string(from: ride.startedAt)
        }
    }

    private var emptyView: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "bicycle")
                .font(.system(size: 64))
                .foregroundColor(Colors.grey400)

            Text("No rides yet")
                .font(Typography.h3)

            Text("Upload your first ride to get started!")
                .font(Typography.body)
                .foregroundColor(Colors.grey700)
        }
    }

    private func errorView(_ error: String) -> some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 48))
                .foregroundColor(Colors.error)

            Text(error)
                .font(Typography.body)
                .foregroundColor(Colors.error)

            Button("Retry") {
                Task { await loadRides() }
            }
            .neoButton(gradient: Gradients.blueCyan)
        }
    }

    private func loadRides() async {
        isLoading = true
        error = nil

        do {
            rides = try await APIClient.shared.listRides()
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }
}

struct RideRowView: View {
    let ride: RideSummary

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(formatDate(ride.startedAt))
                    .font(Typography.bodySmall)
                    .foregroundColor(Colors.black)

                HStack(spacing: Spacing.sm) {
                    Label(formatDistance(ride.distanceM), systemImage: "point.topleft.down.curvedto.point.bottomright.up")
                    Label(formatElevation(ride.elevationGainM), systemImage: "mountain.2")
                }
                .font(Typography.monoSmall)
                .foregroundColor(Colors.grey500)
            }

            Spacer()

            if let dung = ride.dungMinted, dung > 0 {
                HStack(spacing: 4) {
                    Text("🪲")
                    Text("+\(dung)")
                        .font(Typography.h3)
                        .foregroundColor(Colors.orange)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    private func formatDistance(_ meters: Double) -> String {
        let km = meters / 1000
        return String(format: "%.1f km", km)
    }

    private func formatElevation(_ meters: Double) -> String {
        return String(format: "%.0f m", meters)
    }
}
```

**Add to MainTabView:**
```swift
// In BoulderRollersApp.swift, update MainTabView
TabView {
    MapView()
        .tabItem { Label("Map", systemImage: "map") }

    CALView()
        .tabItem { Label("CAL", systemImage: "bitcoinsign.circle") }

    RideUploadView()
        .tabItem { Label("Upload", systemImage: "square.and.arrow.up") }
        .badge(appState.hasProcessingRides || appState.hasCompletedRides ? "!" : nil)

    RidesHistoryView()  // NEW
        .tabItem { Label("Rides", systemImage: "list.bullet") }

    ProfileView()
        .tabItem { Label("Profile", systemImage: "person") }
}
```

---

## Testing Instructions

### Unit Tests

```swift
// ios/BoulderRollersTests/AchievementsTests.swift
import XCTest
@testable import BoulderRollers

class AchievementsTests: XCTestCase {

    func testAchievementIconMapping() {
        let komAchievement = Achievement(
            id: "1",
            achievementType: "kom",
            title: "KOM",
            description: nil,
            value: nil,
            rank: nil,
            createdAt: nil
        )

        XCTAssertEqual(komAchievement.icon, "crown.fill")
        XCTAssertEqual(komAchievement.color, .yellow)
    }

    func testAchievementValueFormatting() {
        // Test time formatting
        let card = AchievementCard(achievement: Achievement(
            id: "1",
            achievementType: "kom",
            title: "KOM",
            description: nil,
            value: 125.0, // 2:05
            rank: nil,
            createdAt: nil
        ))

        // Value should format as "2:05"
        // (Implementation detail test)
    }

    func testDistanceMilestoneFormatting() {
        // Test that 100000 formats as "100 km"
    }
}

class RideHistoryTests: XCTestCase {

    func testRidesGroupedByMonth() {
        let rides = [
            RideSummary(id: "1", startedAt: Date(), distanceM: 50000, elevationGainM: 500, tss: 100, dungMinted: 100, status: "completed"),
            // Add rides from different months
        ]

        // Test grouping logic
    }

    func testEmptyRidesState() {
        // Test that empty state shows correctly
    }
}
```

### UI Tests

```swift
// ios/BoulderRollersUITests/AchievementsUITests.swift
import XCTest

class AchievementsUITests: XCTestCase {

    func testAchievementsViewLoads() {
        let app = XCUIApplication()
        app.launch()

        // Navigate to profile
        app.tabBars.buttons["Profile"].tap()

        // Tap achievements link
        app.buttons["Achievements"].tap()

        // Verify achievements view appears
        XCTAssertTrue(app.staticTexts["ACHIEVEMENTS"].exists)
    }

    func testDungCelebrationAnimation() {
        // Test celebration view appears after ride completion
        // (Requires mock ride completion)
    }
}
```

### Manual Testing Checklist

```markdown
## iOS Features Manual Testing Checklist

### Achievements View
- [ ] Navigate to Profile → Achievements
- [ ] Verify achievements load from API
- [ ] Verify correct icons for each achievement type
- [ ] Verify correct colors for each achievement type
- [ ] Verify value formatting (time, distance, elevation)
- [ ] Test empty state when no achievements
- [ ] Test error state and retry button
- [ ] Test pull-to-refresh

### DUNG Celebration
- [ ] Complete a ride upload
- [ ] Verify confetti animation fires
- [ ] Verify DUNG amount shows prominently
- [ ] Verify scale animation on DUNG text
- [ ] Verify haptic feedback on success
- [ ] Verify metrics card appears after delay
- [ ] Test Share button → Opens Twitter
- [ ] Test Done button → Dismisses view
- [ ] Verify celebration only shows when DUNG > 0

### Rides History
- [ ] Navigate to Rides tab
- [ ] Verify rides load from API
- [ ] Verify rides grouped by month
- [ ] Verify ride row shows: date, distance, elevation, DUNG
- [ ] Tap ride → Navigate to detail view
- [ ] Test pull-to-refresh
- [ ] Test empty state when no rides
- [ ] Test error state and retry

### Integration
- [ ] Upload ride → See celebration → See in history
- [ ] Unlock achievement → See in achievements view
- [ ] Badge appears on Upload tab when processing
- [ ] Badge disappears after clearing completed ride
```

---

## Success Criteria

- [ ] Achievements view shows all user achievements
- [ ] Achievement icons and colors match type
- [ ] DUNG celebration shows confetti and animation
- [ ] Share to Twitter works correctly
- [ ] Rides history shows all past rides
- [ ] Rides grouped by month
- [ ] Navigation between views works smoothly
- [ ] All UI tests pass
- [ ] Manual testing checklist complete

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `ios/.../Models/Achievement.swift` | NEW - Achievement model |
| `ios/.../Views/Profile/AchievementsView.swift` | NEW - Achievements UI |
| `ios/.../Views/Rides/DungCelebrationView.swift` | NEW - Celebration |
| `ios/.../Views/Rides/RidesHistoryView.swift` | NEW - History view |
| `ios/.../Views/Rides/RideUploadView.swift` | Use celebration view |
| `ios/.../Views/Profile/ProfileView.swift` | Add achievements link |
| `ios/.../BoulderRollersApp.swift` | Add Rides tab |
| `ios/BoulderRollers.xcodeproj` | Add ConfettiSwiftUI package |
