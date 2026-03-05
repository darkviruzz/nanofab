# 9. Platform and Non-Functional Requirements

## 9.1 Platform Targets
Minimum:
- Desktop: Linux, macOS, Windows

Optional:
- Mobile: Android/iOS (depending on chosen stack)

## 9.2 Performance and Responsiveness
- UI must remain responsive during heavy steps.
- Background job management required.
- Large artifacts must be streamed/previewed efficiently.

## 9.3 Storage
- File-based storage initially (runs folder).
- URI-based artifact references to enable later remote storage (S3/HTTP).

## 9.4 Robustness
- Forward-compatible state files via schema identifiers and facets.
- Migration strategy between schema versions.

---
