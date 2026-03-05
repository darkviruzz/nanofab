# NanoFab Process Manager — Documentation Index

This index lists the documentation chapters split into separate files.

- **00 — Preface**: Version: 0.2 (consolidated requirements + current mock implementation) Scope: This document describes **the intended product** (full-feature target) while clearly calling out what is currently **mocked / sample data**.  
  File: `00_Preface.md`

- **01 — Principle of the Application**: ## 1.1 Digital Twin and “State Evolution” (Core Principle)  
  File: `01_Principle_of_the_Application.md`

- **02 — Target Use Cases (User Needs)**: ## 2.1 Primary Use Case: Manage a Complex Cleanroom Chain  
  File: `02_Target_Use_Cases_User_Needs.md`

- **03 — System Overview and Architecture**: > Current UI implementation is an Angular dashboard; backend “physics” is currently mocked. The long-term requirement is **Python backend** with an appropriate UI framework for visualization and responsiveness.  
  File: `03_System_Overview_and_Architecture.md`

- **04 — Data Model Specification (Target)**: This section merges the intended `SampleState` schema (extensible, artifact-referenced) with the simplified structure used in the current mock app.  
  File: `04_Data_Model_Specification_Target.md`

- **05 — UI/UX Specification (Target + Current Mock)**: ## 5.1 Layout Model (Desktop and Mobile)  
  File: `05_UI_UX_Specification_Target_Current_Mock.md`

- **06 — Core Features and Functions (Detailed)**: ## 6.1 Process Chain Management  
  File: `06_Core_Features_and_Functions_Detailed.md`

- **07 — Chain of Events: Current Mock Recipe (8-step Lithography + Lift-Off)**: This section documents the **demonstrated** chain and the intended state mutations. This recipe is a template: the architecture must support larger chains and additional inspection insertions.  
  File: `07_Chain_of_Events_Current_Mock_Recipe_8_step_Lithography_Lift_Off.md`

- **08 — Extended Feature Set (Target, Not Yet Implemented)**: ## 8.1 Inspection Step Insertion - “Insert inspection after…” any step. - Inspections produce artifacts and may populate metrology facets (e.g., thickness map).  
  File: `08_Extended_Feature_Set_Target_Not_Yet_Implemented.md`

- **09 — Platform and Non-Functional Requirements**: ## 9.1 Platform Targets Minimum: - Desktop: Linux, macOS, Windows  
  File: `09_Platform_and_Non_Functional_Requirements.md`

- **10 — Implementation Notes (Current Mock)**: The current mock application demonstrates: - process list + status gating - step details view with parameter editing - mismatch warning example - simulated execution with progress + logs - sample state mutation for se...  
  File: `10_Implementation_Notes_Current_Mock.md`

- **11 — Glossary**: - **Recipe**: the defined sequence of steps + parameter schemas. - **Run**: an executed instance of a recipe for a specific sample. - **SampleState**: snapshot of the physical sample (substrate + layers + facets + art...  
  File: `11_Glossary.md`

- **12 — Roadmap (Suggested Milestones)**: 1) **v0 (MVP)** - file-backed run storage (revisions + artifacts) - robust `SampleState` schema + Quantity units - process chain editor + step executor + logs - artifacts browser (images + CSV)  
  File: `12_Roadmap_Suggested_Milestones.md`
