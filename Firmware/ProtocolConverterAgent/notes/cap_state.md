# 🔒 Tube Cap State Management Rules

All workstations in the system follow strict rules regarding tube cap states.
**Only the `solution-preparation` workstation is allowed to change the cap state.**
All other workstations **must receive the correct state** and output without modification.

---

## 1. Cap State Control: Solution-Preparation is the Only Workstation with Cap Modification Capability

### **✔ solution-preparation**

* **Input cap state:** open or closed
* **Output cap state:** explicitly set via parameter (`"open"` / `"closed"`)
* **Role:** Sole controller of tube cap transitions throughout the workflow.

---

## 2. Cap State Requirements: Workstations with Fixed Input and Output States

These workstations **cannot open or close caps**.
They **validate** the input state and **output a fixed state**.

### **✔ centrifuge-purification**

* **Requires input:** closed
* **Outputs:** closed
* Reason: Safe centrifugation and robotic handling require sealed tubes.

---

### **✔ ultrasonic-treatment**

* **Requires input:** open
* **Outputs:** open
* Reason: Ultrasonic processing typically requires open tubes for pressure release.

---

### **✔ oven-station**

* **Requires input:** closed/open
* **Outputs:** closed/open
* Reason: closed for Heating / Aging; open for drying

---

### **✔ electrochemistry-station**

* **Requires input:** open
* **Outputs:** open
* Reason: Electrodes must be inserted into open tubes with accessible electrolyte.

---

## 3. Cap State Management: Workflow Design Principles and Best Practices

1. **Only `solution-preparation` may perform cap opening/closing.**
2. If a workflow needs to switch cap state, insert a `solution-preparation` step—even with an empty ratio table—to set the new state.
3. Each workstation strictly enforces its required input cap state.
4. Each workstation outputs a fixed cap state that cannot be changed internally.

---

## 4. Cap State Management Example: Complete Workflow State Transition Sequence

```
init → solution-preparation (set closed)
↓
centrifuge-purification (closed → closed)
↓
solution-preparation (set open)
↓
electrochemistry-station (open → open)
```
