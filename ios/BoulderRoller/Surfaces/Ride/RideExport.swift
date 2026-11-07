import SwiftUI
import UniformTypeIdentifiers

struct RideFileDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.data] }

    let data: Data

    init(data: Data) {
        self.data = data
    }

    init(configuration: ReadConfiguration) throws {
        data = configuration.file.regularFileContents ?? Data()
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: data)
    }

    static func contentType(for fileType: String) -> UTType {
        switch fileType.lowercased() {
        case "gpx": UTType(filenameExtension: "gpx") ?? .xml
        case "tcx": UTType(filenameExtension: "tcx") ?? .xml
        case "fit": UTType(filenameExtension: "fit") ?? .data
        default: .data
        }
    }
}
