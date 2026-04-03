# 🧪 Liquid Mixing Guide (For Automated Workflow)

Efficient mixing is essential for obtaining uniform reaction mixtures, catalyst inks, and precursor solutions.
In this system, liquid mixing can be achieved through **two mechanisms**:

1. **Magnetic stirring via the `solution-preparation` workstation**
2. **Ultrasonic mixing via the `ultrasonic-treatment` workstation**

The recommended default method is **magnetic stirring**.

---

## 1. Magnetic Stirring via Solution-Preparation (Preferred Method)

The `solution-preparation` workstation integrates a magnetically driven stirring module beneath the tube rack.
This system can provide reliable mixing **without requiring a separate mixing step**.

### ✔ How to enable magnetic stirring

Magnetic stirring is controlled by:

```
mixing_time_min
```

inside the solution-preparation step.

This means the user **does not need a dedicated “mixing” workstation step**—simply include the desired mixing duration in the same step as liquid addition.

**Example usage inside a solution-preparation step:**

```json
"parameters": {
	"ratio_table": "mixing_example.csv",
	"mixing_time_min": 15,
	"tube_cap_state": "open"
}
```

### ✔ When to use magnetic stirring

* Routine mixing of precursor solutions
* Dispersing metal salts or organics into solvent
* Light catalyst dispersions
* Any workflow where ultrasonic power is not explicitly required

In most experiments, **magnetic stirring alone is sufficient**.

---

## 2. Ultrasonic Mixing (Alternative Method)

The `ultrasonic-treatment` workstation provides high-energy cavitation mixing, suitable for breaking aggregates or dispersing nanoparticles.

### ✔ When ultrasonic treatment is recommended

Use ultrasonic mixing **only when specifically needed**, for example:

* Preparing catalyst ink that requires strong dispersion
* Breaking up particulate aggregates
* Enhancing Nafion-assisted dispersion before electrochemical coating

### ✔ Cap-state requirement

Ultrasonic mixing requires tubes to be **open**.
The `solution-preparation` workstation must set the cap state prior to ultrasonic treatment.

---

## 3. General Recommendations

* Unless otherwise specified, **use magnetic stirring** (solution-preparation).
* Use ultrasonic mixing **only when strong dispersion is scientifically necessary**.
* Avoid unnecessary ultrasonic cycles, which may heat samples or cause chemical degradation.
* Always verify tube cap state before ultrasonic or post-mixing steps.

---

## 4. Summary Table

| Mixing Method         | How to Enable                                 | Cap State      | Recommended Usage                  |
| --------------------- | --------------------------------------------- | -------------- | ---------------------------------- |
| **Magnetic stirring** | Set `mixing_time_min` in solution-preparation | open or closed | Default; most liquid mixing tasks  |
| **Ultrasonic mixing** | Use ultrasonic-treatment workstation          | open           | Strong dispersion, Nafion ink prep |

