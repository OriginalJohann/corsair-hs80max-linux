# Instructions for Corsair HS80 Max GNOME Extension Development

## 1. Role & Objective
* **Goal:** Develop a background service and GNOME Extension to display connection status, battery levels, and details for the Corsair HS80 Max headset in the GNOME systray, with interactive features such as opening a volume control application.
* **Target Features:**
  * Fetch connection and battery status from the USB Dongle via service.
  * **GNOME-Extension (min. version 50.4 compatible)**:
    * Display quick status info in the GNOME systray (connected or disconnected, mic on or off, two small icons next to each other dynamically positioned to the left of the systray).
    * Show detailed status information upon clicking the tray icon (battery percentage).
    * Open a volume regulation app via interaction with the connection icon (system standard if possible).
    * Update the in the extension whenever the service updates them or after 30 minutes.

## 2. Communication & Documentation Standards
* **User Communication:** Primary language for chat interface communication is **German**.
* **Code & Documentation:** Write ALL documentation, commit messages, code comments, system notes, and planning files in **English**.
* **User Notifications:** Promptly inform the user whenever the physical headset needs to be powered on or plugged in for live testing.

## 3. Core Functional Requirements
* **Connection:**
  * The headset connects wirelessly via its USB Dongle.
  * Connection, battery and mic state are all sourced from the dongle.
* **Analysis & Resource Handling:**
  * Write all analysis results as Markdown files in the `./resources` folder.
  * Utilize existing files in `./resources` as reference and context sources.
* **NixOS Environment Integration:**
  * Create Nix shell files whenever temporary tools, libraries, or applications are required.
  * Place all custom Nix shell definitions into a dedicated `./shells` directory.

## 4. Execution Guidelines & KI Constraints
* **Adherence to AGENTS.md:** Respect all workspace limits, planning steps (`./plans/`), execution logging (`./scratchpad/`), security rules, and stop conditions defined in `AGENTS.md`.
* **No Unverified Assumptions:** Ask the user before proceeding if data mappings, hardware protocols, or volume mixer integrations are ambiguous.
* **Extension testing:**: Use 'dbus-run-session -- gnome-shell --devkit' for testing because otherwise testing extensions requires a reload of the current shell session which is not possible for you without shutting down.