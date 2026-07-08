# Memristor Device Simulator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Django](https://img.shields.io/badge/django-5.1-green.svg)](https://www.djangoproject.com/)
[![Pixi](https://img.shields.io/badge/env-pixi-orange.svg)](https://pixi.sh/)

A web-based platform for simulating memristive circuits and networks. This application provides an intuitive interface for researchers, students, and engineers to configure, simulate, and analyze memristor behavior without requiring extensive programming knowledge.

> **Note:** This is a fork of the original [memristor_simulation](https://github.com/ignaciopineyro/memristor_simulation) project by Ignacio Piñeyro, with substantial additions. The most important change for existing users is that **the project no longer uses Docker** — the environment (including NGSpice) is now managed with [pixi](https://pixi.sh/). See [Changes in this fork](#changes-in-this-fork) for the full list.

## Table of Contents

- [What is a Memristor?](#what-is-a-memristor)
- [What This Application Does](#what-this-application-does)
- [Changes in this fork](#changes-in-this-fork)
- [Quick Start with Pixi (Recommended)](#quick-start-with-pixi-recommended)
  - [Step 1: Install Pixi](#step-1-install-pixi)
  - [Step 2: Get the Application](#step-2-get-the-application)
  - [Step 3: Set Up the Database](#step-3-set-up-the-database)
  - [Step 4: Run the Application](#step-4-run-the-application)
- [Project Structure](#project-structure)
- [Alternative: Manual Installation](#alternative-manual-installation)
- [Web Interface Usage](#web-interface-usage)
  - [Parameter Sweep](#parameter-sweep)
  - [Simulation Results](#simulation-results)
- [Utility Scripts](#utility-scripts)
- [Running the Tests](#running-the-tests)
- [Contributing](#contributing)
- [License](#license)

---

## What is a Memristor?

A memristor is a passive electronic component that changes its resistance based on the history of current that has flowed through it. This "memory resistance" makes memristors valuable for neuromorphic computing, non-volatile memory, and analog computation applications.

## What This Application Does

- **Circuit Simulation**: Generate and simulate memristive circuits using industry-standard NGSpice
- **Multiple Models**: Support for Pershin and Vourkas memristor models
- **Network Analysis**: Simulate individual devices or complex networks (Grid 2D, Random Regular, Watts-Strogatz, or your own topology via GraphML upload)
- **Ohmic Junction Probability**: Assign a probability `p` of a junction being ohmic (resistive), with a configurable random seed and multiple realizations run in parallel
- **Parameter Sweep**: Sweep over threshold voltage `vt` and/or ohmic-junction probability `p` in a single request
- **Visualization**: Automatic generation of I-V curves, hysteresis loops, and time-domain plots, previewed directly in the browser
- **Export Results**: Download simulation data and plots as organized ZIP files

---

## Changes in this fork

Relative to the upstream project, this fork adds the following:

- **Pixi replaces Docker.** All Docker files (`Dockerfile`, `docker-compose.yml`, `Makefile`, `entrypoint.sh`, etc.) were removed. The environment is now defined in `pixi.toml` / `pixi.lock`, which also installs NGSpice, so there is no separate NGSpice install step.
- **Custom topologies via GraphML.** A new `GRAPHML_UPLOAD` network type lets you upload a `.graphml` file and simulate over an arbitrary network.
- **Ohmic (resistive) junction probability module.** Each junction can be made ohmic with probability `p`, controlled by a random `seed` and an `amount_realizations` count. Realizations run in parallel (up to 5 at a time).
- **Parameter sweep.** Sweep `vt` and/or `p` from the UI — as a comma-separated list or as a start/stop/step range. Each `vt × p` combination runs the full simulation in its own `vt_<vt>_p_<p>` subfolder over a shared network topology, and a `sweep_summary.csv` indexes every combination. Limited to 100 combinations per request.
- **Internal states in a separate CSV.** Simulation results (`<name>_results.csv`) now keep only `time, vin, i(v1)`; internal states are written to `<name>_states.csv`. This keeps result files small even for large networks. Saving states can be forced with `force_save_states`. A migration script (`scripts/split_internal_states.py`) converts old-format files.
- **Gear integration method.** The generated `.cir` files now use `.options method=gear` for improved convergence.
- **In-browser plot viewer.** The backend returns the results ZIP as base64 JSON; the frontend (using JSZip) previews the generated plots on the page in addition to offering the download.

See [`memristorsimulation_app/CHANGELOG.md`](memristorsimulation_app/CHANGELOG.md) for version history.

---

## Quick Start with Pixi (Recommended)

[Pixi](https://pixi.sh/) manages the full environment — Python, all dependencies, and NGSpice — from a single lock file, so you don't need to install Python or NGSpice yourself.

### Step 1: Install Pixi

**Linux / macOS:**
```bash
curl -fsSL https://pixi.sh/install.sh | bash
```

**Windows (PowerShell):**
```powershell
iwr -useb https://pixi.sh/install.ps1 | iex
```

Restart your terminal afterwards so `pixi` is on your PATH. See the [official install guide](https://pixi.sh/latest/#installation) for other options.

### Step 2: Get the Application

**Option A: Clone with Git**
```bash
git clone https://github.com/javidelrojoo/memristor_simulation.git
cd memristor_simulation
```

**Option B: Download ZIP**
1. Go to the [repository page](https://github.com/javidelrojoo/memristor_simulation)
2. Click the green "Code" button and choose "Download ZIP"
3. Extract it and `cd` into the extracted folder

The first `pixi run` command will automatically create the environment from `pixi.lock` (this may take a few minutes the first time).

### Step 3: Set Up the Database

Run the database migrations and collect static files:
```bash
pixi run setup-db
```
Optionally, create an admin user for the Django admin interface:
```bash
pixi run admin
```

### Step 4: Run the Application

```bash
pixi run server
```

Once you see `Starting development server at http://127.0.0.1:8000/`, open your browser at **http://localhost:8000** and start simulating.

**Available pixi tasks** (defined in `pixi.toml`):

| Task | Command | Description |
| --- | --- | --- |
| `migrate` | `pixi run migrate` | Apply database migrations |
| `static` | `pixi run static` | Collect static files |
| `setup-db` | `pixi run setup-db` | Run `migrate` + `static` |
| `admin` | `pixi run admin` | Create a Django superuser |
| `server` | `pixi run server` | Start the development server |

---

## Project Structure

This is a Django web application organized around memristor simulation functionality.

### Django Project

- **`djangoproject/`**: Main Django project configuration
    * `settings.py`: Django configuration (database, static files, apps)
    * `urls.py`: URL routing
    * `wsgi.py` & `asgi.py`: WSGI/ASGI entry points

- **`memristorsimulation_app/`**: Main Django application
    * `models.py`: Django ORM models
    * `views.py`: HTTP request handling (returns the results ZIP as base64 JSON)
    * `admin.py`: Django admin configuration
    * `constants.py`: Enum constants used throughout the project (including the `NetworkType.GRAPHML_UPLOAD` value)
    * `representations.py`: Dataclass representations, including `OhmicJunctionParameters` and `SweepParameters`

### Application Directories

![System diagram](assets/sequenceDiagram.png)

- **`memristorsimulation_app/services/`**: Business logic
    * `simulationservice.py`: Top-level orchestrator — runs single/network/sweep simulations, handles realizations in parallel, and builds the results ZIP
    * `circuitfileservice.py`: Circuit file (`.cir`) generation (subcircuits, components, analysis and control commands, `method=gear` options)
    * `subcircuitfileservice.py`: Subcircuit file (`.sub`) generation with memristor model parameters
    * `networkservice.py`: Network topology generation, including GraphML import and ohmic-junction assignment
    * `plotterservice.py`: Plotting of I-V and State-Time curves and comparative/sub-plot figures
    * `directoriesmanagementservice.py`: Path resolution and folder creation (including sweep subfolders)
    * `ngspiceservice.py`: NGSpice simulation wrapper
    * `timemeasureservice.py`: Simulation time measurement

- **`memristorsimulation_app/simulation_templates/`**: Predefined simulation configurations (single-device variants and network templates)
- **`memristorsimulation_app/models/`**: Memristor model subcircuits (`pershin.sub`, `vourkas.sub`)
- **`memristorsimulation_app/serializers/`**: Django REST Framework serializers, including sweep and ohmic-junction validation
- **`memristorsimulation_app/templates/`**: `form.html` — the web interface with in-browser plot preview
- **`memristorsimulation_app/static/`**: CSS and JavaScript assets
- **`memristorsimulation_app/tests/`**: Test suite (services, serializers, and `test_sweep.py`)
- **`memristorsimulation_app/simulation_results/`**: Simulation output storage. Each run creates subdirectories with `<name>_results.csv` (`time, vin, i(v1)`), `<name>_states.csv` (internal states), generated plots, and logs.

### Root-Level Files

- **`manage.py`**: Django management script
- **`pixi.toml`** / **`pixi.lock`**: Pixi environment definition and lock file (dependencies + NGSpice + tasks)
- **`requirements.txt`**: Python dependencies (for the manual pip-based install)
- **`db.sqlite3`**: SQLite database file
- **`scripts/`**: Utility scripts (see [Utility Scripts](#utility-scripts))
- **`memristorsimulation_app/CHANGELOG.md`**: Version history

---

## Alternative: Manual Installation

If you prefer not to use pixi, you can install everything manually (Python 3.10, NGSpice, a virtual environment, and `pip install -r requirements.txt`). Detailed instructions are in the [Manual Installation Guide](MANUAL_INSTALLATION.md).

**Note**: The manual route requires installing NGSpice yourself and troubleshooting environment/PATH issues. Pixi is recommended for most users because it handles all of that for you.

---

## Web Interface Usage

The Django web interface provides a form for configuring and running simulations:

1. **Model Configuration:** Select memristor model (Pershin or Vourkas). Both share the same set of parameters.
2. **Input Parameters:** Source name and connection nodes
3. **Waveform Configuration:** Configure voltage waveforms (SIN, PULSE, PWL)
4. **Simulation Parameters:** Simulation type, time steps, voltages, and device parameters
5. **Export Parameters:** Folder and file name, and magnitudes to export
6. **Network Configuration:** Single device, a generated topology (Grid 2D, Random Regular, Watts-Strogatz), or a **GraphML upload** of your own network
7. **Ohmic Junction Probability:** Probability `p` of ohmic junctions, a random `seed`, and the number of realizations (run in parallel)
8. **Plotter:** Select plot types (some depend on the chosen network type)
9. **Execute Simulation:** Click "Run Simulation" to execute, preview the plots in the browser, and download the results as a ZIP

### Parameter Sweep

Instead of a single value, you can sweep the threshold voltage `vt` and/or the ohmic-junction probability `p`:

- Provide values as a **comma-separated list** (e.g. `0.1, 0.2, 0.3`) or as a **start / stop / step range**
- Every `vt × p` combination runs the full simulation — including all realizations — over the same network topology
- Each combination is saved in its own `vt_<vt>_p_<p>` subfolder, and a `sweep_summary.csv` indexes them all
- Sweeps are limited to **100 combinations** per request

### Simulation Results

- Execution time scales with circuit complexity (number of devices) and the number of realizations/combinations
- Results are packaged as a ZIP and previewed in the browser
- Each run includes `<name>_results.csv` (I-V data), `<name>_states.csv` (internal states), generated plots, and simulation logs
- Persistent storage maintains simulation history

---

## Utility Scripts

- **`scripts/split_internal_states.py`**: Migrates old-format result files to the new layout. Older `<name>_results.csv` files stored the internal states inline, producing very large files. This script splits them into `<name>_results.csv` (`time, vin, i(v1)`) and `<name>_states.csv` (internal states), leaving files that already follow the new format untouched.

  ```bash
  # Processes memristorsimulation_app/simulation_results by default
  pixi run python scripts/split_internal_states.py [path_to_simulation_results]
  ```

---

## Running the Tests

```bash
pixi run pytest
```

The suite covers the services, serializers, and the parameter-sweep logic (`test_sweep.py`).

---

## Contributing

This is an open-source educational project — contributions are welcome! Whether you're a student, researcher, or engineer, your input is valuable.

**Ways to contribute:**
- **Bug Reports**: Found an issue? Please open an Issue
- **Feature Requests**: Have ideas for new simulation capabilities? Let us know
- **Documentation**: Help improve guides, tutorials, or code documentation
- **Code Contributions**: Submit pull requests for bug fixes or new features

**Getting started:**
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/NewFeature`)
3. Make your changes and add tests if applicable
4. Commit your changes (`git commit -m 'Added new feature X'`)
5. Push to the branch (`git push origin feature/NewFeature`)
6. Open a Pull Request

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

**What this means:**
- Free to use for academic, educational, and research purposes
- Free to modify and adapt for your specific needs
- Free to distribute and share with others
- Free for commercial use
- Attribution required: please credit this project when using it in academic work

---

#### Original project by Ignacio Piñeyro — ignaciopineyroo@gmail.com — *Buenos Aires, Argentina*
#### Fork maintained by Javier ([@javidelrojoo](https://github.com/javidelrojoo))
