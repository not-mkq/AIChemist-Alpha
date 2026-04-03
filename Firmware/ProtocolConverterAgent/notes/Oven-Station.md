# 🔥 Oven-Station Usage Guide (Short Version)

The Oven-Station provides controlled heating, aging, and drying functions.
Its behavior depends on tube cap state **and solvent safety constraints**.

---

## 1. Oven-Station Requirements: Tube Cap State for Heating and Drying

The Oven-Station **cannot change tube cap state**.
It only accepts tubes in the correct state and preserves that state when finished.

| Purpose         | Input Cap State | Output Cap State | Notes                                             |
| --------------- | --------------- | ---------------- | ------------------------------------------------- |
| Heating / Aging | **closed**      | **closed**       | Required to prevent evaporation and contamination |
| Drying          | **open**        | **open**         | Only allowed when no organic solvent is present   |

To switch cap states, the workflow **must insert a solution-preparation step**, even if no liquid is added.

---

## 2. Oven-Station Constraints: Temperature Safety and Boiling Point Rules

### **The oven temperature must never exceed the boiling point of the solvent in the tube.**

Because this is a closed system during heating/aging:

* Heating above the solvent’s boiling point can create dangerous overpressure
* Risk of tube rupture, leakage, or ejection

If solvent type is known, the workflow or operator must ensure:

```
temperature_C <= solvent_boiling_point
```

---

## 3. Oven-Station Constraints: Organic Solvent Drying Restrictions

### ❌ Organic solvents cannot be dried in this station.

Drying requires the tube to be open, but open drying of organic solvents is unsafe due to:

* High vapor concentration
* Flammability risk
* Potential damage to equipment

Oven drying is permitted **only for water or inorganic solvent systems** after organics have been removed elsewhere.

---

## 4. Oven-Station Arguments: Required Parameters Summary

```
duration_min: integer
temperature_C: integer
sealed: boolean    # Indicates operator intent only; does NOT change tube cap state
```

Final cap state always matches the **input** tube cap state.

---

## 5. Oven-Station Example: Heating and Aging JSON Configuration

```json
{
	"step_id": 4,
	"workstation_id": "oven-station",
	"batch_time_s": 14400,
	"parameters": {
		"duration_min": 240,
		"temperature_C": 80
	}
}
```

**Input requirement:** closed tube

---

## 6. Oven-Station Example: Drying Process JSON Configuration

```json
{
	"step_id": 6,
	"workstation_id": "oven-station",
	"batch_time_s": 7200,
	"parameters": {
		"duration_min": 120,
		"temperature_C": 60
	}
}
```

**Input requirement:** open tube
**Solvent requirement:** no organic solvent present
