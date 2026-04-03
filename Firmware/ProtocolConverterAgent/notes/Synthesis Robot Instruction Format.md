# 🧪 **Synthesis Robot Instruction Format (with Examples)**

This document describes the human-readable specification for robotic synthesis workflows.
A workflow is a sequence of **steps**, each executed at a predefined workstation.

---

# ## 1. Top-Level Structure

```yaml
steps:
- step_id: 1
workstation_id: solution-preparation
batch_time_s: 1800
parameters: {...}
- step_id: 2
workstation_id: ultrasonic-treatment
batch_time_s: 600
parameters: {...}
```

---

# ## 2. Workstation Definitions & Required Parameters

Each workstation includes a short **example case**.

---

# ### 2.1 **solution-preparation**

### Parameters

| Name              | Type    | Required | Description                               |
| ----------------- | ------- | -------- | ----------------------------------------- |
| `ratio_table`     | string  | ✔        | Path to CSV prepared by `ratio_generator` |
| `mixing_time_min` | integer | ✔        | Post-dispensing mixing time               |

### **Example**

```yaml
step_id: 1
workstation_id: solution-preparation
batch_time_s: 1800
parameters:
ratio_table: "ratios/exp_batch1.csv"
mixing_time_min: 10
```

---

# ### 2.2 **centrifuge-purification**

### Parameters

| Name           | Type    | Required | Description                        |
| -------------- | ------- | -------- | ---------------------------------- |
| `speed_rpm`    | integer | ✔        | ≤ 10000 rpm                        |
| `duration_min` | integer | ✔        | Centrifugation duration            |
| `wash_times`   | integer | optional | Washing cycles (1–5)               |
| `retain_phase` | enum    | ✔        | `"supernatant"` or `"precipitate"` |

### **Example**

```yaml
step_id: 2
workstation_id: centrifuge-purification
batch_time_s: 900
parameters:
speed_rpm: 8000
duration_min: 10
wash_times: 2
retain_phase: "precipitate"
```

---

# ### 2.3 **ultrasonic-treatment**

### Parameters

| Name           | Type    | Required | Description                   |
| -------------- | ------- | -------- | ----------------------------- |
| `duration_min` | integer | ✔        | Ultrasonic duration           |
| `power`        | enum    | ✔        | `"low"`, `"medium"`, `"high"` |

### **Example**

```yaml
step_id: 3
workstation_id: ultrasonic-treatment
batch_time_s: 600
parameters:
duration_min: 5
power: "medium"
```

---

# ### 2.4 **oven-station**

### Parameters

| Name            | Type    | Required | Description                 |
| --------------- | ------- | -------- | --------------------------- |
| `duration_min`  | integer | ✔        | Heating time                |
| `temperature_C` | integer | ✔        | Oven temperature            |

### **Example**

```yaml
step_id: 4
workstation_id: oven-station
batch_time_s: 3600
parameters:
duration_min: 60
temperature_C: 80
```

---

# ### 2.5 **electrochemistry-station**

### Parameters

| Name         | Type        | Required | Description                      |
| ------------ | ----------- | -------- | -------------------------------- |
| `test_types` | array(enum) | ✔        | Any of: `"CV"`, `"LSV"`, `"EIS"` |

### **Example**

```yaml
step_id: 5
workstation_id: electrochemistry-station
batch_time_s: 2400
parameters:
test_types: ["CV", "EIS"]
```

---

# ## 3. Summary Table

| Workstation              | Required Params                       | Optional Params | Example Step    |
| ------------------------ | ------------------------------------- | --------------- | --------------- |
| solution-preparation     | ratio_table, mixing_time_min          | –               | Example in §2.1 |
| centrifuge-purification  | speed_rpm, duration_min, retain_phase | wash_times      | §2.2            |
| ultrasonic-treatment     | duration_min, power                   | –               | §2.3            |
| oven-station             | duration_min, temperature_C           | sealed          | §2.4            |
| electrochemistry-station | test_types                            | –               | §2.5            |

