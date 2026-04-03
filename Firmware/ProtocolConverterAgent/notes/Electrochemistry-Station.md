# ⚡ Electrochemistry-Station Pre-Requirements

The Electrochemistry-Station performs automated CV, LSV, EIS, and related electrochemical measurements.
Before a sample is allowed to enter this station, **all of the following conditions must be satisfied** to ensure stable catalyst loading and reliable test results.

---

## 1. Electrochemistry-Station Requirements: Nafion Addition and Ultrasonic Mixing Prerequisites

To ensure strong adhesion of the catalyst ink to the carbon paper, the sample **must** undergo:

1. **Addition of Nafion solution** (prepared by the operator in advance)
2. **Ultrasonic mixing** to ensure uniform dispersion

These steps are *not* performed at the Electrochemistry-Station.
They must be completed in earlier workflow steps.

Typical required sequence:

```
solution-preparation (add Nafion → open)
↓
ultrasonic-treatment (mixing → open)
↓
electrochemistry-station
```

The station will reject any sample that has not been properly mixed.

---

## 2. Electrochemistry-Station Capabilities: Fixed 1 cm² Coating Area Specification

This station uses a standardized carbon paper substrate with a **fixed active coating area of 1 cm²**.

* The robot dispenses the ink onto this predefined region.
* Operators do not need to specify area parameters.
* All subsequent drying or preparation routines follow this fixed geometry.

---

## 3. Electrochemistry-Station Requirements: Tube Cap State Must Be Open

The Electrochemistry-Station only accepts tubes in the **open** state:

```
required input cap state: open  
output cap state: open
```

Because this station does **not** have cap-opening capability,
any closed tube must first be passed through a `solution-preparation` step to switch cap state:

```
solution-preparation (set cap = open)
↓
electrochemistry-station
```

If the tube is closed upon arrival, the task is rejected.

---

## 4. Electrochemistry-Station Requirements: Pre-Programmed Test Parameters

The station does not infer or generate measurement parameters.
Instead:

* CV / LSV / EIS / chronoamperometry profiles must be **pre-programmed by the operator** in the instrument software.
* The robot executes:

* Catalyst ink dispensing
* Carbon paper handling
* Electrode installation
* Launching the preloaded test sequence
* Data collection

The workflow JSON does *not* need to specify scan rates, potentials, frequency lists, etc.

---

# ✔ Summary Table

| Requirement              | Must Be Satisfied Before Entry | Performed by This Station |
| ------------------------ | ------------------------------ | ------------------------- |
| Nafion addition          | ✔                              | ✘                         |
| Ultrasonic mixing        | ✔ (ultrasonic-treatment)       | ✘                         |
| Fixed coating area 1 cm² | ✔                              | ✔                         |
| Tube open state          | ✔                              | ✘                         |
| Test program definition  | ✔ (operator)                   | ✘                         |

