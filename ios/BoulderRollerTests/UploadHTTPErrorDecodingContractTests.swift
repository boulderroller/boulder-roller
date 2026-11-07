import Foundation
import XCTest
@testable import BoulderRoller

final class UploadHTTPErrorDecodingContractTests: XCTestCase {
    func testBackendFileMissingDetailReachesTypedHTTPError() throws {
        let body = Data(
            #"{"detail":{"error":"file_missing","message":"File not found in storage. Upload may have failed or expired."}}"#.utf8
        )

        let error = APIClient.httpError(status: 400, body: body)

        guard case let .http(status, code, message) = error else {
            return XCTFail("structured upload detail must remain an HTTP error")
        }
        XCTAssertEqual(status, 400)
        XCTAssertEqual(code, "file_missing")
        XCTAssertEqual(message, "File not found in storage. Upload may have failed or expired.")
    }
}
