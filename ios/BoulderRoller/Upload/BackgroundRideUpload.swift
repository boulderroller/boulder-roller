import Foundation

/// File-backed transfer used by the persisted ride-upload lifecycle. The
/// background session owns the network request after `resume()`, so an
/// eligible transfer can continue while the app is suspended or relaunched.
/// The persisted source snapshot is read only; multipart framing is written to
/// a separate temporary file and removed after URLSession finishes the task.
final class BackgroundRideFileTransfer: NSObject, RideFileTransferring, @unchecked Sendable {
    static let sessionIdentifier = "com.boulderroller.app.ride-upload"

    private let fileManager: FileManager
    private let bodyDirectoryURL: URL
    private let beforeUploadPublish: @Sendable () -> Void
    private let afterUploadBodyWritten: @Sendable () -> Void
    private let afterUploadTaskResumed: @Sendable () -> Void
    private let beforeTaskCompletion: @Sendable () -> Void
    private let lock = NSLock()
    private var continuations: [Int: CheckedContinuation<Void, Error>] = [:]
    private var activeTaskJobIDs: [Int: String] = [:]
    private var frozenJobIDs: Set<String> = []
    private var backgroundEventCompletions: [@Sendable () -> Void] = []
    private var sessionStorage: URLSession!

    private var session: URLSession { sessionStorage }

    init(
        fileManager: FileManager = .default,
        bodyDirectoryURL: URL? = nil,
        sessionIdentifier: String = BackgroundRideFileTransfer.sessionIdentifier,
        beforeUploadPublish: @escaping @Sendable () -> Void = {},
        afterUploadBodyWritten: @escaping @Sendable () -> Void = {},
        afterUploadTaskResumed: @escaping @Sendable () -> Void = {},
        beforeTaskCompletion: @escaping @Sendable () -> Void = {}
    ) {
        self.fileManager = fileManager
        self.beforeUploadPublish = beforeUploadPublish
        self.afterUploadBodyWritten = afterUploadBodyWritten
        self.afterUploadTaskResumed = afterUploadTaskResumed
        self.beforeTaskCompletion = beforeTaskCompletion
        self.bodyDirectoryURL = bodyDirectoryURL
            ?? fileManager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("RideUploadBodies", isDirectory: true)
        super.init()

        let configuration = URLSessionConfiguration.background(
            withIdentifier: sessionIdentifier
        )
        configuration.sessionSendsLaunchEvents = true
        configuration.isDiscretionary = false
        configuration.waitsForConnectivity = true
        sessionStorage = URLSession(
            configuration: configuration,
            delegate: self,
            delegateQueue: nil
        )
    }

    func isActive(jobID: String) async -> Bool {
        await withCheckedContinuation { continuation in
            session.getAllTasks { tasks in
                let active = tasks.contains { task in
                    task.taskDescription == jobID
                        && (
                            task.state == .running
                                || task.state == .suspended
                                || task.state == .canceling
                        )
                }
                continuation.resume(returning: active)
            }
        }
    }

    func upload(
        jobID: String,
        signedURL: String,
        sourceURL: URL,
        fileName: String
    ) async throws {
        guard UUID(uuidString: jobID) != nil,
              let destinationURL = URL(string: signedURL)
        else {
            throw URLError(.badURL)
        }

        // The coordinator checks this before calling upload. Retain the guard
        // here as well so a resumed lifecycle cannot create a second task for
        // the same persisted logical upload.
        guard !(await isActive(jobID: jobID)) else { return }
        beforeUploadPublish()

        try await withCheckedThrowingContinuation { continuation in
            var didResumeTask = false
            lock.withLock {
                do {
                    guard !frozenJobIDs.contains(jobID) else {
                        throw AccountDeletionLocalCleanupError.verificationFailed
                    }
                    let boundary = "br-\(UUID().uuidString.lowercased())"
                    let bodyURL = bodyURL(for: jobID)
                    try writeMultipartBody(
                        sourceURL: sourceURL,
                        fileName: fileName,
                        boundary: boundary,
                        destinationURL: bodyURL
                    )
                    afterUploadBodyWritten()

                    var request = URLRequest(url: destinationURL)
                    request.httpMethod = "PUT"
                    request.setValue("false", forHTTPHeaderField: "x-upsert")
                    request.setValue(
                        "multipart/form-data; boundary=\(boundary)",
                        forHTTPHeaderField: "Content-Type"
                    )
                    let task = session.uploadTask(with: request, fromFile: bodyURL)
                    task.taskDescription = jobID
                    continuations[task.taskIdentifier] = continuation
                    activeTaskJobIDs[task.taskIdentifier] = jobID
                    task.resume()
                    didResumeTask = true
                } catch {
                    continuation.resume(throwing: error)
                }
            }
            if didResumeTask { afterUploadTaskResumed() }
        }
    }

    func cancel(jobIDs: Set<String>) async throws {
        guard !jobIDs.isEmpty else { return }
        guard jobIDs.allSatisfy({ UUID(uuidString: $0) != nil }) else {
            throw URLError(.badURL)
        }
        // Publication and the deletion fence share one lock. A transfer is
        // either fully registered before this point and therefore awaited,
        // or observes the frozen ID and cannot create a body or URLSession task.
        lock.withLock { frozenJobIDs.formUnion(jobIDs) }
        let tasks = await allTasks()
        for task in tasks where task.taskDescription.map(jobIDs.contains) == true {
            task.cancel()
        }
        try await waitForCompletionCallbacks(jobIDs: jobIDs)
        try await waitForSessionTasksToDisappear(jobIDs: jobIDs)
        try lock.withLock {
            for jobID in jobIDs {
                let body = bodyURL(for: jobID)
                if fileManager.fileExists(atPath: body.path) {
                    try fileManager.removeItem(at: body)
                }
                guard !fileManager.fileExists(atPath: body.path) else {
                    throw AccountDeletionLocalCleanupError.verificationFailed
                }
            }
        }
    }

    private func allTasks() async -> [URLSessionTask] {
        await withCheckedContinuation { continuation in
            session.getAllTasks { continuation.resume(returning: $0) }
        }
    }

    /// The delegate callback is the completion boundary for tasks created by
    /// this process. A `.canceling` task is still active and cannot be treated
    /// as safe merely because `cancel()` returned.
    private func waitForCompletionCallbacks(jobIDs: Set<String>) async throws {
        let deadline = Date().addingTimeInterval(10)
        while lock.withLock({ activeTaskJobIDs.values.contains(where: jobIDs.contains) }) {
            guard Date() < deadline else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    /// Background-session tasks restored after process death are not present
    /// in the in-memory callback map. A fresh URLSession inventory is the
    /// second barrier for those tasks.
    private func waitForSessionTasksToDisappear(jobIDs: Set<String>) async throws {
        let deadline = Date().addingTimeInterval(10)
        while true {
            let remaining = await allTasks().contains { task in
                task.taskDescription.map(jobIDs.contains) == true
                    && (task.state == .running
                        || task.state == .suspended
                        || task.state == .canceling)
            }
            if !remaining { return }
            guard Date() < deadline else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    /// Every multipart body is rider source data. Unknown names, directories,
    /// or bodies without a persisted job are handled by the runtime as
    /// unattributed support evidence; they are never globally swept.
    func persistedBodyJobIDs() async throws -> Set<String> {
        guard fileManager.fileExists(atPath: bodyDirectoryURL.path) else { return [] }
        let entries = try fileManager.contentsOfDirectory(
            at: bodyDirectoryURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        var result: Set<String> = []
        for entry in entries {
            guard (try entry.resourceValues(forKeys: [.isDirectoryKey])).isDirectory != true,
                  entry.pathExtension == "multipart"
            else { throw AccountDeletionLocalCleanupError.verificationFailed }
            let jobID = entry.deletingPathExtension().lastPathComponent
            guard UUID(uuidString: jobID) != nil, result.insert(jobID).inserted else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
        }
        return result
    }

    /// Called by the app delegate's background-URLSession handoff. Returns
    /// false for identifiers owned by another subsystem.
    @discardableResult
    func handleEvents(
        forBackgroundURLSession identifier: String,
        completionHandler: @escaping @Sendable () -> Void
    ) -> Bool {
        guard identifier == Self.sessionIdentifier else { return false }
        lock.withLock {
            backgroundEventCompletions.append(completionHandler)
        }
        return true
    }

    private func bodyURL(for jobID: String) -> URL {
        bodyDirectoryURL.appendingPathComponent("\(jobID).multipart", isDirectory: false)
    }

    private func writeMultipartBody(
        sourceURL: URL,
        fileName: String,
        boundary: String,
        destinationURL: URL
    ) throws {
        try fileManager.createDirectory(
            at: bodyDirectoryURL,
            withIntermediateDirectories: true,
            attributes: [
                .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication,
            ]
        )

        let safeFileName = fileName
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "\"", with: "_")
            .replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
        let header = "--\(boundary)\r\n"
            + "Content-Disposition: form-data; name=\"file\"; "
            + "filename=\"\(safeFileName)\"\r\n"
            + "Content-Type: application/octet-stream\r\n"
            + "\r\n"
        let footer = "\r\n--\(boundary)--\r\n"

        guard fileManager.createFile(
            atPath: destinationURL.path,
            contents: nil,
            attributes: [
                .protectionKey: FileProtectionType.completeUntilFirstUserAuthentication,
            ]
        ) else {
            throw CocoaError(.fileWriteUnknown)
        }

        let input = try FileHandle(forReadingFrom: sourceURL)
        let output = try FileHandle(forWritingTo: destinationURL)
        do {
            try output.truncate(atOffset: 0)
            try output.write(contentsOf: Data(header.utf8))
            while let chunk = try input.read(upToCount: 64 * 1024), !chunk.isEmpty {
                try output.write(contentsOf: chunk)
            }
            try output.write(contentsOf: Data(footer.utf8))
            try input.close()
            try output.close()
        } catch {
            try? input.close()
            try? output.close()
            try? fileManager.removeItem(at: destinationURL)
            throw error
        }
    }
}

extension BackgroundRideFileTransfer: URLSessionTaskDelegate, URLSessionDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        beforeTaskCompletion()
        if let jobID = task.taskDescription {
            try? fileManager.removeItem(at: bodyURL(for: jobID))
        }

        let result: Result<Void, Error>
        if let error {
            result = .failure(error)
        } else {
            let status = (task.response as? HTTPURLResponse)?.statusCode ?? 0
            if (200..<300).contains(status) {
                result = .success(())
            } else {
                result = .failure(
                    APIError.http(
                        status: status,
                        code: "storage_upload_failed",
                        message: nil
                    )
                )
            }
        }

        let continuation = lock.withLock {
            activeTaskJobIDs.removeValue(forKey: task.taskIdentifier)
            return continuations.removeValue(forKey: task.taskIdentifier)
        }
        continuation?.resume(with: result)
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        let completions = lock.withLock {
            let current = backgroundEventCompletions
            backgroundEventCompletions.removeAll()
            return current
        }
        DispatchQueue.main.async {
            completions.forEach { $0() }
        }
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
