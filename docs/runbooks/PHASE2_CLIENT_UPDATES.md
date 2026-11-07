# Phase 2: Client Updates Runbook

## Worker Assignment
**Focus:** iOS & Web Portal updates for raw file upload, status polling, new endpoints
**FLAGS:** 7, 8, 10

**Prerequisites:** Backend FLAGS 1-6 must be complete (async processing working)

---

## Overview

Update iOS and Web Portal to:
1. Send raw files to backend (not parsed metrics)
2. Poll for processing status
3. Display activity streams and achievements
4. Consume new API endpoints

---

## FLAG 7: iOS - Raw File Upload

### 7.1 Update APIClient Upload Method

**File:** `ios/BoulderRollers/Services/APIClient.swift`

Replace the current `uploadRide()` method:

```swift
// MARK: - Rides (Updated for server-side processing)

struct RideUploadRequest: Codable {
    let fileDataB64: String
    let fileType: String  // "fit", "gpx", "tcx"
}

struct RideUploadResponse: Codable {
    let rideId: String
    let status: String  // "processing", "queued"
    let message: String
}

struct RideStatusResponse: Codable {
    let rideId: String
    let status: String  // "processing", "completed", "failed"
    let errorMessage: String?
    let metrics: RideMetrics?
    let dungMinted: Int?
    let txSignature: String?

    struct RideMetrics: Codable {
        let tss: Double?
        let kcals: Double?
        let distanceM: Double?
        let elevationGainM: Double?
        let durationSec: Int?
        let avgPowerW: Double?
        let maxPowerW: Int?
        let normalizedPowerW: Double?
        let avgHrBpm: Double?
        let maxHrBpm: Int?
    }
}

/// Upload a ride file for server-side processing
/// - Parameter fileURL: URL to the ride file (GPX, FIT, TCX)
/// - Returns: Upload response with ride ID and status
func uploadRide(fileURL: URL) async throws -> RideUploadResponse {
    // Read file data
    let started = fileURL.startAccessingSecurityScopedResource()
    defer {
        if started {
            fileURL.stopAccessingSecurityScopedResource()
        }
    }

    let fileData = try Data(contentsOf: fileURL)
    let base64Data = fileData.base64EncodedString()

    // Determine file type from extension
    let fileType: String
    switch fileURL.pathExtension.lowercased() {
    case "fit":
        fileType = "fit"
    case "gpx":
        fileType = "gpx"
    case "tcx":
        fileType = "tcx"
    default:
        throw APIError.invalidFileType
    }

    let request = RideUploadRequest(
        fileDataB64: base64Data,
        fileType: fileType
    )

    return try await post("/rides/upload", body: request)
}

/// Poll for ride processing status
/// - Parameter rideId: ID of the ride to check
/// - Returns: Current status and metrics if complete
func getRideStatus(rideId: String) async throws -> RideStatusResponse {
    try await get("/rides/\(rideId)/status")
}

/// Get activity stream for a ride
/// - Parameters:
///   - rideId: ID of the ride
///   - streamType: Type of stream ("power", "heart_rate", "cadence", "speed")
func getActivityStream(rideId: String, streamType: String) async throws -> ActivityStreamResponse {
    try await get("/rides/\(rideId)/streams?type=\(streamType)")
}

struct ActivityStreamResponse: Codable {
    let streamType: String
    let timestamps: [Date]
    let values: [Double]
    let sampleCount: Int
    let minValue: Double?
    let maxValue: Double?
    let avgValue: Double?
}

/// Get user achievements
func getAchievements() async throws -> [Achievement] {
    struct Response: Codable {
        let achievements: [Achievement]
    }
    let response: Response = try await get("/users/me/achievements")
    return response.achievements
}

struct Achievement: Codable, Identifiable {
    let id: String
    let achievementType: String
    let title: String
    let description: String?
    let value: Double?
    let rank: Int?
    let createdAt: Date?
}

// Add to APIError enum
enum APIError: LocalizedError {
    case requestFailed(status: Int, body: String?)
    case invalidResponse
    case invalidFileType  // NEW

    var errorDescription: String? {
        switch self {
        case .requestFailed(let status, let body):
            if let body, !body.isEmpty {
                return "Request failed (\(status)): \(body)"
            }
            return "Request failed (\(status))"
        case .invalidResponse:
            return "Invalid response from server"
        case .invalidFileType:
            return "Unsupported file type. Please upload a .fit, .gpx, or .tcx file."
        }
    }
}
```

### 7.2 Update RideUploadView with Processing Status

**File:** `ios/BoulderRollers/Views/Rides/RideUploadView.swift`

```swift
import SwiftUI
import UniformTypeIdentifiers

struct RideUploadView: View {
    @State private var selectedFileURL: URL?
    @State private var isFilePickerPresented = false
    @State private var uploadState: UploadState = .idle
    @State private var currentRideId: String?
    @State private var completedRide: APIClient.RideStatusResponse?
    @State private var pollingTask: Task<Void, Never>?

    enum UploadState {
        case idle
        case uploading
        case processing(progress: String)
        case completed
        case failed(error: String)
    }

    var body: some View {
        VStack(spacing: Spacing.lg) {
            headerSection

            switch uploadState {
            case .idle:
                selectFileSection
            case .uploading:
                uploadingSection
            case .processing(let progress):
                processingSection(progress: progress)
            case .completed:
                completedSection
            case .failed(let error):
                failedSection(error: error)
            }

            Spacer()
        }
        .padding()
        .fileImporter(
            isPresented: $isFilePickerPresented,
            allowedContentTypes: [.fitDocument, .gpxDocument, .tcxDocument, .data],
            allowsMultipleSelection: false
        ) { result in
            handleFileSelection(result)
        }
        .onDisappear {
            pollingTask?.cancel()
        }
    }

    // MARK: - Sections

    private var headerSection: some View {
        VStack(spacing: Spacing.sm) {
            Text("UPLOAD RIDE")
                .font(Typography.h1)
            Text("Upload your ride file to earn DUNG")
                .font(Typography.body)
                .foregroundColor(Colors.grey700)
        }
    }

    private var selectFileSection: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "doc.badge.plus")
                .font(.system(size: 64))
                .foregroundColor(Colors.blue)

            Text("Select a .FIT, .GPX, or .TCX file")
                .font(Typography.body)

            Button {
                isFilePickerPresented = true
            } label: {
                Text("SELECT FILE")
                    .frame(maxWidth: .infinity)
            }
            .neoButton(gradient: Gradients.blueCyan)
        }
        .padding()
    }

    private var uploadingSection: some View {
        VStack(spacing: Spacing.md) {
            ProgressView()
                .scaleEffect(1.5)
            Text("Uploading file...")
                .font(Typography.body)
        }
    }

    private func processingSection(progress: String) -> some View {
        VStack(spacing: Spacing.md) {
            ProgressView()
                .scaleEffect(1.5)
            Text("Processing your ride...")
                .font(Typography.h3)
            Text(progress)
                .font(Typography.bodySmall)
                .foregroundColor(Colors.grey700)
            Text("This may take a minute for longer rides")
                .font(Typography.bodySmall)
                .foregroundColor(Colors.grey500)
        }
    }

    private var completedSection: some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundColor(Colors.success)

            Text("Ride Processed!")
                .font(Typography.h2)

            if let ride = completedRide {
                rideMetricsCard(ride)

                if let dung = ride.dungMinted, dung > 0 {
                    HStack {
                        Image(systemName: "sparkles")
                        Text("+\(dung) DUNG earned!")
                            .font(Typography.h3)
                    }
                    .foregroundColor(Colors.orange)
                }
            }

            Button {
                resetToIdle()
            } label: {
                Text("UPLOAD ANOTHER")
                    .frame(maxWidth: .infinity)
            }
            .neoButton(gradient: Gradients.blueCyan)
        }
    }

    private func failedSection(error: String) -> some View {
        VStack(spacing: Spacing.md) {
            Image(systemName: "xmark.circle.fill")
                .font(.system(size: 64))
                .foregroundColor(Colors.error)

            Text("Processing Failed")
                .font(Typography.h2)

            Text(error)
                .font(Typography.body)
                .foregroundColor(Colors.error)
                .multilineTextAlignment(.center)

            Button {
                resetToIdle()
            } label: {
                Text("TRY AGAIN")
                    .frame(maxWidth: .infinity)
            }
            .neoButton(gradient: Gradients.orangeYellow)
        }
    }

    private func rideMetricsCard(_ ride: APIClient.RideStatusResponse) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            if let metrics = ride.metrics {
                HStack {
                    metricItem(value: formatDuration(metrics.durationSec ?? 0), label: "Duration")
                    Spacer()
                    metricItem(value: formatDistance(metrics.distanceM ?? 0), label: "Distance")
                    Spacer()
                    metricItem(value: formatElevation(metrics.elevationGainM ?? 0), label: "Elevation")
                }

                Divider()

                HStack {
                    metricItem(value: String(format: "%.0f", metrics.tss ?? 0), label: "TSS")
                    Spacer()
                    metricItem(value: String(format: "%.0f", metrics.kcals ?? 0), label: "Calories")
                    Spacer()
                    if let np = metrics.normalizedPowerW {
                        metricItem(value: String(format: "%.0f W", np), label: "NP")
                    } else {
                        metricItem(value: "-", label: "NP")
                    }
                }
            }
        }
        .padding()
        .neoCard()
    }

    private func metricItem(value: String, label: String) -> some View {
        VStack {
            Text(value)
                .font(Typography.h3)
            Text(label)
                .font(Typography.monoSmall)
                .foregroundColor(Colors.grey600)
        }
    }

    // MARK: - Actions

    private func handleFileSelection(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            selectedFileURL = url
            uploadFile(url)
        case .failure(let error):
            uploadState = .failed(error: error.localizedDescription)
        }
    }

    private func uploadFile(_ url: URL) {
        uploadState = .uploading

        Task {
            do {
                // Upload file
                let response = try await APIClient.shared.uploadRide(fileURL: url)
                currentRideId = response.rideId

                // Start polling for status
                uploadState = .processing(progress: "Analyzing ride data...")
                startPolling(rideId: response.rideId)

            } catch {
                uploadState = .failed(error: error.localizedDescription)
            }
        }
    }

    private func startPolling(rideId: String) {
        pollingTask?.cancel()

        pollingTask = Task {
            var attempts = 0
            let maxAttempts = 60  // 5 minutes max

            while !Task.isCancelled && attempts < maxAttempts {
                do {
                    let status = try await APIClient.shared.getRideStatus(rideId: rideId)

                    switch status.status {
                    case "completed":
                        await MainActor.run {
                            completedRide = status
                            uploadState = .completed
                        }
                        return

                    case "failed":
                        await MainActor.run {
                            uploadState = .failed(error: status.errorMessage ?? "Processing failed")
                        }
                        return

                    case "processing":
                        await MainActor.run {
                            uploadState = .processing(progress: "Calculating metrics...")
                        }

                    default:
                        break
                    }

                } catch {
                    // Continue polling on network errors
                }

                attempts += 1
                try? await Task.sleep(nanoseconds: 5_000_000_000)  // 5 seconds
            }

            // Timeout
            await MainActor.run {
                uploadState = .failed(error: "Processing timed out. Please try again.")
            }
        }
    }

    private func resetToIdle() {
        pollingTask?.cancel()
        selectedFileURL = nil
        currentRideId = nil
        completedRide = nil
        uploadState = .idle
    }

    // MARK: - Formatters

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

// File type declarations
extension UTType {
    static var fitDocument: UTType {
        UTType(filenameExtension: "fit") ?? .data
    }
    static var gpxDocument: UTType {
        UTType(filenameExtension: "gpx") ?? .xml
    }
    static var tcxDocument: UTType {
        UTType(filenameExtension: "tcx") ?? .xml
    }
}
```

### 7.3 Remove Client-Side Parsing from Upload Flow

The `RideFileParser.swift` can remain for local preview purposes, but should **NOT** be used in the upload flow. The upload now sends raw file data directly to the server.

---

## FLAG 8: Web Portal - Raw File Upload

### 8.1 Update RideUploadModal

**File:** `web/portal/src/components/RideUploadModal.tsx`

```typescript
import { useState, useCallback, useEffect } from 'react';
import { useApi } from '../hooks/useApi';

interface RideUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (ride: RideStatusResponse) => void;
}

interface RideStatusResponse {
  rideId: string;
  status: 'processing' | 'completed' | 'failed';
  errorMessage?: string;
  metrics?: {
    tss: number;
    kcals: number;
    distanceM: number;
    elevationGainM: number;
    durationSec: number;
    avgPowerW?: number;
    maxPowerW?: number;
    normalizedPowerW?: number;
  };
  dungMinted?: number;
  txSignature?: string;
}

export function RideUploadModal({ isOpen, onClose, onSuccess }: RideUploadModalProps) {
  const api = useApi();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<'idle' | 'uploading' | 'processing' | 'completed' | 'failed'>('idle');
  const [currentRideId, setCurrentRideId] = useState<string | null>(null);
  const [completedRide, setCompletedRide] = useState<RideStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // File selection handler
  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      const ext = file.name.split('.').pop()?.toLowerCase();
      if (!['fit', 'gpx', 'tcx'].includes(ext || '')) {
        setError('Please select a .fit, .gpx, or .tcx file');
        return;
      }
      setSelectedFile(file);
      setError(null);
    }
  }, []);

  // Upload handler
  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setUploadState('uploading');
    setError(null);

    try {
      // Read file as base64
      const base64 = await fileToBase64(selectedFile);
      const fileType = selectedFile.name.split('.').pop()?.toLowerCase() || 'fit';

      // Upload to server
      const response = await api.post('/rides/upload', {
        file_data_b64: base64,
        file_type: fileType,
      });

      setCurrentRideId(response.ride_id);
      setUploadState('processing');

    } catch (err: any) {
      setError(err.message || 'Upload failed');
      setUploadState('failed');
    }
  }, [selectedFile, api]);

  // Polling effect
  useEffect(() => {
    if (uploadState !== 'processing' || !currentRideId) return;

    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 60;

    const poll = async () => {
      while (!cancelled && attempts < maxAttempts) {
        try {
          const status = await api.get<RideStatusResponse>(`/rides/${currentRideId}/status`);

          if (status.status === 'completed') {
            setCompletedRide(status);
            setUploadState('completed');
            onSuccess(status);
            return;
          }

          if (status.status === 'failed') {
            setError(status.errorMessage || 'Processing failed');
            setUploadState('failed');
            return;
          }

        } catch (err) {
          // Continue polling on network errors
        }

        attempts++;
        await new Promise(resolve => setTimeout(resolve, 5000));
      }

      // Timeout
      setError('Processing timed out. Please try again.');
      setUploadState('failed');
    };

    poll();

    return () => {
      cancelled = true;
    };
  }, [uploadState, currentRideId, api, onSuccess]);

  // Reset handler
  const handleReset = () => {
    setSelectedFile(null);
    setUploadState('idle');
    setCurrentRideId(null);
    setCompletedRide(null);
    setError(null);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
        <h2 className="text-xl font-bold mb-4">Upload Ride</h2>

        {uploadState === 'idle' && (
          <div className="space-y-4">
            <input
              type="file"
              accept=".fit,.gpx,.tcx"
              onChange={handleFileSelect}
              className="w-full"
            />
            {selectedFile && (
              <p className="text-sm text-gray-600">
                Selected: {selectedFile.name}
              </p>
            )}
            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}
            <div className="flex gap-2">
              <button
                onClick={handleUpload}
                disabled={!selectedFile}
                className="flex-1 bg-blue-600 text-white py-2 rounded disabled:opacity-50"
              >
                Upload
              </button>
              <button
                onClick={onClose}
                className="flex-1 bg-gray-200 py-2 rounded"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {uploadState === 'uploading' && (
          <div className="text-center py-8">
            <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto mb-4" />
            <p>Uploading file...</p>
          </div>
        )}

        {uploadState === 'processing' && (
          <div className="text-center py-8">
            <div className="animate-spin w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto mb-4" />
            <p className="font-medium">Processing your ride...</p>
            <p className="text-sm text-gray-500 mt-2">
              This may take a minute for longer rides
            </p>
          </div>
        )}

        {uploadState === 'completed' && completedRide && (
          <div className="space-y-4">
            <div className="text-center">
              <div className="text-4xl mb-2">✅</div>
              <p className="font-medium">Ride Processed!</p>
            </div>

            {completedRide.metrics && (
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <p className="text-lg font-bold">
                    {formatDuration(completedRide.metrics.durationSec)}
                  </p>
                  <p className="text-xs text-gray-500">Duration</p>
                </div>
                <div>
                  <p className="text-lg font-bold">
                    {(completedRide.metrics.distanceM / 1000).toFixed(1)} km
                  </p>
                  <p className="text-xs text-gray-500">Distance</p>
                </div>
                <div>
                  <p className="text-lg font-bold">
                    {completedRide.metrics.elevationGainM?.toFixed(0)} m
                  </p>
                  <p className="text-xs text-gray-500">Elevation</p>
                </div>
              </div>
            )}

            {completedRide.dungMinted && completedRide.dungMinted > 0 && (
              <p className="text-center text-orange-600 font-bold">
                +{completedRide.dungMinted} DUNG earned! 💰
              </p>
            )}

            <button
              onClick={handleReset}
              className="w-full bg-blue-600 text-white py-2 rounded"
            >
              Upload Another
            </button>
          </div>
        )}

        {uploadState === 'failed' && (
          <div className="space-y-4">
            <div className="text-center">
              <div className="text-4xl mb-2">❌</div>
              <p className="font-medium">Processing Failed</p>
              <p className="text-sm text-red-600 mt-2">{error}</p>
            </div>
            <button
              onClick={handleReset}
              className="w-full bg-gray-200 py-2 rounded"
            >
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// Helpers
async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // Remove data URL prefix (e.g., "data:application/octet-stream;base64,")
      const base64 = result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}
```

### 8.2 Add Activity Streams Visualization

**File:** `web/portal/src/components/ActivityChart.tsx`

```typescript
import { useEffect, useState } from 'react';
import { useApi } from '../hooks/useApi';

interface ActivityChartProps {
  rideId: string;
  streamType: 'power' | 'heart_rate' | 'cadence' | 'speed';
}

interface StreamData {
  streamType: string;
  timestamps: string[];
  values: number[];
  minValue: number;
  maxValue: number;
  avgValue: number;
}

export function ActivityChart({ rideId, streamType }: ActivityChartProps) {
  const api = useApi();
  const [data, setData] = useState<StreamData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<StreamData>(`/rides/${rideId}/streams?type=${streamType}`)
      .then(setData)
      .finally(() => setLoading(false));
  }, [rideId, streamType, api]);

  if (loading) {
    return <div className="h-32 bg-gray-100 animate-pulse rounded" />;
  }

  if (!data || data.values.length === 0) {
    return (
      <div className="h-32 bg-gray-100 rounded flex items-center justify-center text-gray-500">
        No {streamType.replace('_', ' ')} data available
      </div>
    );
  }

  // Simple SVG line chart
  const width = 400;
  const height = 100;
  const padding = 10;

  const xScale = (i: number) => padding + (i / (data.values.length - 1)) * (width - 2 * padding);
  const yScale = (v: number) => height - padding - ((v - data.minValue) / (data.maxValue - data.minValue)) * (height - 2 * padding);

  const pathData = data.values
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(v)}`)
    .join(' ');

  const labels: Record<string, string> = {
    power: 'Power (W)',
    heart_rate: 'Heart Rate (bpm)',
    cadence: 'Cadence (rpm)',
    speed: 'Speed (m/s)',
  };

  return (
    <div className="bg-white rounded p-4">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-medium">{labels[streamType]}</span>
        <span className="text-xs text-gray-500">
          Avg: {data.avgValue.toFixed(0)} | Max: {data.maxValue.toFixed(0)}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
        <path
          d={pathData}
          fill="none"
          stroke="#3B82F6"
          strokeWidth="2"
        />
      </svg>
    </div>
  );
}
```

---

## FLAG 10: New API Endpoints

### 10.1 Add Endpoints to Backend

**File:** `backend/app/routes/rides.py` (add these)

```python
@router.get("/{ride_id}/streams")
async def get_ride_streams(
    ride_id: str,
    type: str = Query(..., description="Stream type: power, heart_rate, cadence, speed"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get activity stream data for a ride."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    stream = await repo.get_activity_stream(UUID(ride_id), type)
    if not stream:
        raise HTTPException(status_code=404, detail=f"No {type} stream found")

    return stream


@router.get("/{ride_id}/gps")
async def get_ride_gps(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get GPS track for a ride."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    points = await repo.get_gps_track(UUID(ride_id))
    return {"gps_points": points}


@router.get("/{ride_id}/segments")
async def get_ride_segments(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get matched segment efforts for a ride."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    efforts = await repo.get_ride_segment_efforts(UUID(ride_id))
    return {"segments": efforts}
```

**File:** `backend/app/routes/users.py` (add achievement endpoint)

```python
@router.get("/me/achievements")
async def get_my_achievements(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    limit: int = Query(50, ge=1, le=100),
):
    """Get user's achievements."""
    achievements = await repo.get_user_achievements(
        current_user.user_id,
        limit=limit,
    )
    return {"achievements": achievements}
```

---

## Testing Checklist

### iOS
- [ ] File picker accepts .fit, .gpx, .tcx files
- [ ] File is base64 encoded and sent to server
- [ ] Upload returns ride_id immediately
- [ ] Polling shows processing status
- [ ] Completed ride displays metrics
- [ ] DUNG earned is displayed
- [ ] Failed uploads show error message
- [ ] "Upload Another" resets state

### Web Portal
- [ ] File input accepts correct file types
- [ ] File is base64 encoded correctly
- [ ] Processing state shows spinner
- [ ] Completed state shows metrics
- [ ] Activity chart loads stream data
- [ ] Error states handled gracefully

### API Endpoints
- [ ] `GET /rides/{id}/status` returns correct status
- [ ] `GET /rides/{id}/streams?type=power` returns stream data
- [ ] `GET /rides/{id}/gps` returns GPS points
- [ ] `GET /rides/{id}/segments` returns matched efforts
- [ ] `GET /users/me/achievements` returns achievements

---

## Deployment Notes

1. **Deploy Backend First:** Ensure all backend FLAGs (1-6) are complete before deploying client changes
2. **Feature Flag:** Consider adding a feature flag to toggle between old (sync) and new (async) upload paths during transition
3. **Backwards Compatibility:** Old clients sending pre-calculated metrics will fail - coordinate app release with backend deployment
