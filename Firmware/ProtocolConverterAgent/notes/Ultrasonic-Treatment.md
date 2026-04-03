# 🔊 Ultrasonic-Treatment Workstation Manual (Draft v1)

## 1. Ultrasonic-Treatment Workstation: Overview and Capabilities

The *ultrasonic-treatment* workstation performs sonication on the sample.
It is typically used for dispersion, cleaning, or breaking aggregated particles.
The workstation executes a single ultrasonic cycle according to the specified:

* **duration_min** (treatment time)
* **power** (low / medium / high)

This module has no complex liquid-handling or separation behavior.

---

## 2. Ultrasonic-Treatment Requirements: Tube Cap State Must Be Open

This workstation **cannot open or close tube caps**.
Due to pressure fluctuations and vapor release during sonication:

```
Input tube must be:  open
Output tube will remain: open
```

If the tube is closed when entering this step, the system will reject the task.

To open tubes prior to sonication, insert a `solution-preparation` step with:

```json
"tube_cap_state": "open"
```

---

## 3. Ultrasonic-Treatment Arguments: Required Parameters Specification

| Parameter    | Type        | Description                      |
| ------------ | ----------- | -------------------------------- |
| duration_min | integer     | Sonication time in minutes       |
| power        | string enum | `"low"`, `"medium"`, or `"high"` |

During execution, the robot will:

1. Place the tube in the ultrasonic bath
2. Set the ultrasound intensity according to `power`
3. Run for `duration_min`
4. Retrieve the tube, keeping it open

---

## 4. Ultrasonic-Treatment Example: JSON Workflow Configuration

```json
{
	"step_id": 4,
	"workstation_id": "ultrasonic-treatment",
	"batch_time_s": 600,
	"parameters": {
		"duration_min": 10,
		"power": "medium"
	}
}
```

---

## 5. Ultrasonic-Treatment Best Practices: Operational Recommendations

* **Medium power for 5–15 minutes** is sufficient for most dispersion tasks.
* For volatile or foam-prone systems, reduce time or choose a lower power.
* If the next step requires a closed tube (e.g., centrifuge or oven), insert a `solution-preparation` step afterward to set `"tube_cap_state": "closed"`.

