# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Parameter sweep over vt (threshold) and p (ohmic junction probability) from the web UI. Values can be given as a comma-separated list or as a start/stop/step range. Each vt × p combination runs the full simulation (including multiple realizations) in a `vt_<vt>_p_<p>` subfolder sharing the same network topology, and a `sweep_summary.csv` indexes all combinations. Limited to 100 combinations per request.

## [1.0.0] - 2025-Nov-11

### Added
- Initial release of Memristor Device Simulator
- Web-based interface for memristor circuit simulation
- Support for Pershin and Vourkas memristor models
- Network topology simulation (Grid 2D, Random Regular, Watts-Strogatz)
- Multiple waveform types (SIN, PULSE, PWL)
- Automatic plot generation (I-V curves, time domain plots)
- Docker containerization for easy deployment
- Comprehensive test suite with GitHub Actions CI/CD
- MIT License for open-source collaboration

### Technical Features
- Django 5.1 web framework
- NGSpice integration for circuit simulation
- Matplotlib for data visualization
- NetworkX for network topology generation
- Docker Compose for development environment
- GitHub Actions for automated testing
- Responsive web form
