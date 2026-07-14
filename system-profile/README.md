# Amosclaud system profile

This folder contains optional, user-controlled workstation settings for running Amosclaud on a personal computer or Minisforum server.

The profile never applies itself automatically. Use `install-profile.ps1` on Windows or `install-profile.sh` on Linux. Both installers:

- support a preview/dry-run mode
- back up an existing file before replacing it
- link only files listed in the installer
- avoid secrets and machine-specific credentials
- support removal by deleting the created links and restoring the backup

The Amosclaud application and local model work without this profile. It is only for consistent shell and Git behavior.
