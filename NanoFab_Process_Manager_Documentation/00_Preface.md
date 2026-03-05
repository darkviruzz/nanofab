# NanoFab Process Manager — Application Documentation (Merged Spec)

Version: 0.2 (consolidated requirements + current mock implementation)  
Scope: This document describes **the intended product** (full-feature target) while clearly calling out what is currently **mocked / sample data**.

---

## 0. Executive Summary

**NanoFab Process Manager** is a process-chain orchestration and visualization application for micro/nano-fabrication R&D workflows. It is designed to behave as a **Digital Twin**: the app maintains a versioned, physically meaningful **SampleState** of a substrate (wafer/chip/coupon) and evolves that state through a sequence of modular process steps. Each step is parameterized, validated against the current state, executed asynchronously (non-blocking), and produces persisted artifacts (images, tables, reports, 3D surfaces) that can be browsed and compared.

The current codebase/UI demonstrates the architecture using mocked execution and a mock 8-step lithography + lift-off recipe. The same architecture is intended to scale to larger, real-world cleanroom chains (dozens of steps, multiple inspections, complex simulations).

---
