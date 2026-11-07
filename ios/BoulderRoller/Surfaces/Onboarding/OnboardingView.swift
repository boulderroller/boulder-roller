import SwiftUI

/// Surface 1 — Onboarding. The name, the door, and one line of the Wall as
/// decoration. No taglines (Law 9: copy here is Tim's to write or omit).
struct OnboardingView: View {
    @Environment(AppSession.self) private var session

    @State private var showEmailFlow = false
    @State private var showInviteEntry = false
    @State private var inviteCode: String = ""
    @State private var busy = false
    @State private var errorMessage: String?

    var body: some View {
        ZStack {
            Theme.screen.ignoresSafeArea()

            // One blue profile line as decoration.
            WallLine()
                .stroke(Theme.blue.opacity(0.5), style: StrokeStyle(lineWidth: 2, lineCap: .round))
                .frame(height: 120)
                .offset(y: -60)
                .accessibilityHidden(true)

            VStack {
                Spacer()
                Text("Boulder Roller")
                    .font(.title.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .padding(.bottom, 120)
                Spacer()

                VStack(spacing: 10) {
                    // Truthful session-end notice (expiry after long
                    // offline, server revocation) — system string, no
                    // apology, no mechanism. Absent on ordinary arrivals.
                    if let notice = session.sessionEndNotice {
                        Text(notice)
                            .font(.footnote)
                            .foregroundStyle(Theme.gray)
                            .multilineTextAlignment(.center)
                            .padding(.bottom, 6)
                    }

                    Button {
                        signInWithApple()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "applelogo")
                            Text("Sign in with Apple")
                        }
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.black)
                        .frame(maxWidth: .infinity, minHeight: 48)
                        .background(Capsule().fill(Theme.ink))
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)

                    Button {
                        showEmailFlow = true
                    } label: {
                        Text("Continue with email")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(Theme.ink)
                            .frame(maxWidth: .infinity, minHeight: 46)
                            .overlay(Capsule().stroke(.white.opacity(0.22), lineWidth: 0.5))
                            .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(busy)

                    Button {
                        showInviteEntry = true
                    } label: {
                        Text(
                            "\(Text("Have an invite code?").foregroundStyle(Theme.gray2)) \(Text(inviteCode.isEmpty ? "Enter it" : inviteCode).foregroundStyle(Theme.gray))"
                        )
                        .font(.caption)
                    }
                    .buttonStyle(.plain)
                    .padding(.top, 14)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 36)
            }

            #if DEBUG
            VStack {
                HStack {
                    Spacer()
                    Button("DEV") { devSignIn() }
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(Theme.gray3)
                        .padding(.trailing, 20)
                        .padding(.top, 8)
                        .accessibilityLabel("Developer sign in")
                }
                Spacer()
            }
            #endif

            if busy {
                ProgressView().tint(Theme.gray)
            }
        }
        .sheet(isPresented: $showEmailFlow) {
            EmailSignInSheet(inviteCode: nonEmptyInvite)
        }
        .sheet(isPresented: $showInviteEntry) {
            InviteCodeSheet(code: $inviteCode)
        }
        .alert(
            "Sign in failed", isPresented: .init(
                get: { errorMessage != nil }, set: { if !$0 { errorMessage = nil } }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(errorMessage ?? "")
        }
    }

    private var nonEmptyInvite: String? {
        inviteCode.isEmpty ? nil : inviteCode
    }

    private func signInWithApple() {
        busy = true
        Task {
            defer { busy = false }
            do {
                try await session.signInWithApple(inviteCode: nonEmptyInvite)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    #if DEBUG
    private func devSignIn() {
        busy = true
        Task {
            defer { busy = false }
            do {
                try await session.devSignIn()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
    #endif
}

/// The decorative profile line (the Wall), from the ratified surface gallery.
private struct WallLine: Shape {
    func path(in rect: CGRect) -> Path {
        let pts: [(CGFloat, CGFloat)] = [
            (-10, 100), (40, 94), (80, 84), (120, 66), (160, 44),
            (200, 26), (240, 16), (280, 11), (350, 8),
        ]
        var path = Path()
        let sx = rect.width / 340.0
        let sy = rect.height / 120.0
        path.move(to: CGPoint(x: pts[0].0 * sx, y: pts[0].1 * sy))
        for p in pts.dropFirst() {
            path.addLine(to: CGPoint(x: p.0 * sx, y: p.1 * sy))
        }
        return path
    }
}

/// Email OTP flow: address, then code. Field labels only — no explainer prose.
private struct EmailSignInSheet: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    var inviteCode: String?

    @State private var email = ""
    @State private var code = ""
    @State private var codeSent = false
    @State private var busy = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                if !codeSent {
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } else {
                    TextField("Code", text: $code)
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                }
                if let errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundStyle(Theme.gray)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.sheet)
            .navigationTitle("Continue with email")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(Theme.blue)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if busy {
                        ProgressView()
                    } else {
                        Button(codeSent ? "Sign in" : "Send code") { advance() }
                            .fontWeight(.semibold)
                            .foregroundStyle(Theme.blue)
                            .disabled(codeSent ? code.isEmpty : email.isEmpty)
                    }
                }
            }
        }
        .presentationDetents([.medium])
        .presentationCornerRadius(Theme.crown)
    }

    private func advance() {
        busy = true
        errorMessage = nil
        Task {
            defer { busy = false }
            do {
                if !codeSent {
                    try await PrivyAuthService.shared.sendEmailCode(to: email)
                    codeSent = true
                } else {
                    try await session.confirmEmailCode(code, email: email, inviteCode: inviteCode)
                    dismiss()
                }
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}

private struct InviteCodeSheet: View {
    @Binding var code: String
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField("Invite code", text: $draft)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }
            .scrollContentBackground(.hidden)
            .background(Theme.sheet)
            .navigationTitle("Invite code")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(Theme.blue)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        code = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                        dismiss()
                    }
                    .fontWeight(.semibold)
                    .foregroundStyle(Theme.blue)
                }
            }
        }
        .presentationDetents([.medium])
        .presentationCornerRadius(Theme.crown)
        .onAppear { draft = code }
    }
}
