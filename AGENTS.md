# StabilityConsole development

The current interface direction is a modern Matrix-inspired black-and-green workspace. The previous Khorne red-and-brass styling is retired. Use the shared palette and widget states in `StabilityConsole-v0.1.0/theme.py`; keep body text readable, keyboard focus visible and primary actions easy to find. Keep the main pages accessible from the sidebar and preserve action controls when resizing the window.

Start the app through the repository-root `Launch-StabilityConsole.bat`. Keep the historical source-folder path compatible. Run the existing launcher checks and exercise the real Tk workflow for UI changes. CI screenshots must contain temporary demonstration records only.

Candidate reports, email data, credentials, documents and local databases stay private and must never be committed to this public repository. An interface update must preserve the existing import, approval and mail-evidence rules described in the README.
