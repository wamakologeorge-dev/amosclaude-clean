# Amosclaud Native Support App

This directory contains the native Android support application for Amosclaud.

## Purpose

The app is a mobile support/control surface for Amosclaud rather than a copy of the autonomous engine. It is designed to surface repository health, support events, human approval requests, verification results, and future GitHub App notifications.

## Security model

- No GitHub App private key is stored in the APK.
- No GitHub personal access token or production credential is embedded in source code.
- Privileged GitHub operations remain server-side.
- The app must use authenticated, short-lived user-scoped sessions when the Amosclaud backend is connected.
- Cleartext network traffic is disabled.
- Android backup is disabled for the application.

## Current native features

- Native Kotlin Android project
- Amosclaud Support dashboard
- Native support-service entry point
- Notification permission handling for modern Android versions
- Human-approval center placeholder aligned with Amosclaud approval issues
- Secure backend integration boundary

## Planned integration

1. Amosclaud account/GitHub authentication
2. Repository status and CI health
3. Human approval request notifications
4. Approve/deny actions routed through the Amosclaud backend
5. Pull-request review summaries
6. Fix/test/verification result notifications
7. GitHub App installation status

## Build

Open `mobile/android` in Android Studio using JDK 17 and an Android SDK with API 35 installed.

The repository intentionally does not commit signing keys or production credentials.
