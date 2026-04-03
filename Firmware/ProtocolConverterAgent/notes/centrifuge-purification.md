# 🌀 Centrifuge-Purification Workstation Manual (Full Version v2, English)

## 1. Centrifuge-Purification Workstation: Purpose and Capabilities Overview

The Centrifuge-Purification workstation integrates:

* **A high-speed centrifuge (up to 10,000 rpm)**
* **A robotic arm for tube handling**
* **An automated liquid-handling module (black box operation)**

to perform fully automated purification procedures.

It is designed for:

* Solid–liquid separation of suspensions
* Automatically collecting either the *supernatant* or *precipitate* according to `retain_phase`
* Performing 1–5 washing cycles with user-prepared solvents
* Delivering purified samples ready for the next workstation

Because centrifugation involves **high-speed mechanical motion**, this module strictly requires that all tubes be **closed** upon entry to ensure operational safety.

---

## 2. Centrifuge-Purification Requirements: Tube Cap State Must Be Closed

*(This workstation cannot modify tube-cap states.)*

The Centrifuge-Purification workstation **only accepts tubes that are already closed**:

```
tube_cap_state == "closed"
```

### ❗ This workstation cannot:

* open tube caps
* close tube caps
* change the cap state in any way

Any cap-state changes **must be handled by the Solution-Preparation workstation** earlier in the workflow.

Examples:

* If the tube needs to be closed before centrifugation → add a Solution-Preparation step with `tube_cap_state: "closed"`.
* If the next workstation requires open tubes → add another Solution-Preparation step after centrifugation with `tube_cap_state: "open"`.

A “dummy” ratio table (0 mL addition) can be used to create cap-state-only steps when no liquid addition is needed.

---

## 3. Centrifuge-Purification Capabilities: Speed and Duration Parameters

### ✔ Maximum speed: **10,000 rpm**

Allowed range:

```
0 < speed_rpm ≤ 10,000
```

Exceeding 10,000 rpm → the system rejects the task.
Very low speeds (e.g., < 2,000 rpm) may not produce meaningful separation but are technically allowed.

### ✔ Centrifugation duration: `duration_min`

Unit: minutes.
Typical values: 5–15 min depending on sample viscosity.

---

## 4. Centrifuge-Purification Capabilities: Supernatant and Precipitate Retention Logic

The workstation supports two purification modes:

```
retain_phase: "supernatant" | "precipitate"
```

### retain_phase = "supernatant"

Procedure:

1. Centrifuge → phase separation
2. Remove the pellet
3. Retain the supernatant
4. If `wash_times` is defined, washing cycles are applied to the supernatant (rarely used)

### retain_phase = "precipitate"

Procedure:

1. Centrifuge → phase separation
2. Remove the supernatant
3. Retain the pellet
4. Perform washing cycles if `wash_times > 0`

These two modes cover all common purification scenarios.

---

## 5. Centrifuge-Purification Capabilities: Automated Washing Function and Cycles

Parameter:

```
wash_times: 1–5
```

Values outside this range are not allowed.

Washing cycle:

1. Add washing solvent into the tube
2. Mix the sample
3. Centrifuge
4. Remove supernatant
5. Repeat until all cycles are completed

### Default washing solvent: **Ethanol**

All solvents must be **prepared manually** before the experiment.
The workstation only performs automated dispensing and removal.

---

## 6. Centrifuge-Purification Constraints: Strict Tube Cap State Rules

### Required input state:

```
closed
```

### Output state (always the same):

```
closed
```

This workstation **does not** modify cap states.

All cap-state transitions must be explicitly defined using the Solution-Preparation workstation.

---

## 7. Centrifuge-Purification Arguments: Complete Parameter Specification

| Parameter    | Type    | Required | Description                        |
| ------------ | ------- | -------- | ---------------------------------- |
| speed_rpm    | integer | ✔        | Centrifuge speed (≤10,000 rpm)     |
| duration_min | integer | ✔        | Centrifugation time in minutes     |
| wash_times   | integer | optional | Number of washing cycles (1–5)     |
| retain_phase | enum    | ✔        | `"supernatant"` or `"precipitate"` |

Tube-cap logic requirement:

```
tube_cap_state must be "closed"
```

---

## 8. Centrifuge-Purification Workflow: Internal Execution Steps

1. Robotic arm transfers closed tubes into the centrifuge
2. Centrifugation: `speed_rpm` + `duration_min`
3. Workstation removes the selected phase according to `retain_phase`
4. If washing is requested (`wash_times > 0`):

* Add washing solvent
* Mix
* Centrifuge
* Remove supernatant
5. Repeat until all washing cycles are finished
6. Tubes are returned to the rack **still closed**

---

## 9. Centrifuge-Purification Example: JSON Workflow Configuration

```json
{
	"step_id": 3,
	"workstation_id": "centrifuge-purification",
	"batch_time_s": 1500,
	"parameters": {
		"speed_rpm": 9000,
		"duration_min": 12,
		"wash_times": 3,
		"retain_phase": "precipitate"
	}
}
```

A prior step must ensure the tube is closed:

```json
{
	"workstation_id": "solution-preparation",
	"parameters": {
		"ratio_table": "dummy_empty.csv",
		"mixing_time_min": 0,
		"tube_cap_state": "closed"
	}
}
```

If the subsequent step requires open tubes, add another Solution-Preparation step to open the tubes.

---

## 10. Centrifuge-Purification Best Practices: Operational Recommendations

### ✔ Treat tube-cap state as part of a *workflow state machine*

Because only Solution-Preparation can change caps, you must explicitly place cap-transition steps.
Implicit transitions will cause the workflow to fail.

### ✔ More washing cycles → longer total runtime

Each washing cycle typically adds ~3–5 minutes.

### ✔ Maximum speed is not always the best choice

10,000 rpm is the hardware limit, not the general recommendation.
Many precipitates (e.g., LDH-type materials) centrifuge best at 6,000–9,000 rpm.
