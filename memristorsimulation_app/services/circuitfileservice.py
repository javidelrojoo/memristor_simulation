import os
from typing import TextIO, List
from memristorsimulation_app.representations import (
    InputParameters,
    SimulationParameters,
    DeviceParameters,
)
from memristorsimulation_app.services.directoriesmanagementservice import (
    DirectoriesManagementService,
)
from memristorsimulation_app.services.subcircuitfileservice import SubcircuitFileService


class CircuitFileService:
    # NGSpice truncates control-block command lines longer than ~512 chars,
    # which makes wrdata fail silently on large networks. Keep each wrdata
    # command safely below that limit by splitting magnitudes across several
    # wrdata commands (part files merged after the simulation).
    MAX_WRDATA_LINE_LENGTH = 450

    # Magnitudes that belong to the IV results file. Everything else in
    # export_parameters.magnitudes is treated as an internal state and goes
    # to the separate *_states.csv file.
    IV_MAGNITUDES = ("vin", "i(v1)")

    def __init__(
        self,
        subcircuit_file_service: SubcircuitFileService,
        input_parameters: InputParameters,
        device_parameters: List[DeviceParameters],
        simulation_parameters: SimulationParameters,
        directories_management_service: DirectoriesManagementService,
        ignore_states: bool = None,
    ):
        self.input_parameters = input_parameters
        self.device_parameters = device_parameters
        self.simulation_parameters = simulation_parameters
        self.ignore_states = ignore_states if ignore_states is not None else None

        self.subcircuit_file_service = subcircuit_file_service
        self.directories_management_service = directories_management_service

    def _write_dependencies(self, f: TextIO) -> None:
        f.write("\n\n* DEPENDENCIES:\n")
        # Extract just the filename so NGSpice doesn't choke on path spaces
        subcircuit_filename = os.path.basename(
            self.directories_management_service.get_subcircuit_file_path()
        )
        f.write(f".include {subcircuit_filename}")

    def _write_components(self, file: TextIO) -> None:
        file.write("\n\n* COMPONENTS:\n")
        file.write(self.input_parameters.get_voltage_source_as_string())
        for device_parameter in self.device_parameters:
            file.write(f"{device_parameter.get_device()}\n")
        file.write(".options method=gear\n")

    def _write_analysis_commands(self, file: TextIO) -> None:
        file.write("\n\n* ANALYSIS COMMANDS:\n")
        file.write(self.simulation_parameters.get_analysis())

    def _write_control_commands(self, file: TextIO) -> None:
        file.write("\n\n* CONTROL COMMANDS:\n")
        file.write(".control\n")
        file.write("run\n")
        file.write("set wr_vecnames\n")
        file.write("set wr_singlescale\n")

        # Extract just the filenames for wrdata. The IV magnitudes (time as
        # scale, vin, i(v1)) always go to the light *_results.csv file, while
        # the internal states go to a separate *_states.csv file so that
        # opening an IV curve does not require loading every state column.
        export_filename = os.path.basename(
            self.directories_management_service.get_export_simulation_file_path()
        )
        states_filename = os.path.basename(
            self.directories_management_service.get_export_states_file_path()
        )

        file.write(f"wrdata {export_filename} vin i(v1)\n")

        if not self.ignore_states:
            state_magnitudes = [
                magnitude
                for magnitude in (
                    self.directories_management_service.export_parameters.magnitudes
                )
                if magnitude not in self.IV_MAGNITUDES
            ]
            for wrdata_command in self._build_wrdata_commands(
                states_filename, state_magnitudes
            ):
                file.write(f"{wrdata_command}\n")

    def _build_wrdata_commands(
        self, export_filename: str, magnitudes: List[str]
    ) -> List[str]:
        """
        Builds one or more wrdata commands so that no command line exceeds
        MAX_WRDATA_LINE_LENGTH (NGSpice silently truncates long control lines).
        The first chunk writes to export_filename; the following ones write to
        <name>_part<N>.csv files, which are merged into export_filename after
        the simulation (see TimeMeasureService).
        """
        if not magnitudes:
            return []

        file_stem, file_extension = os.path.splitext(export_filename)

        # Worst-case fixed length per command: "wrdata <name>_part<NN>.csv "
        prefix_allowance = (
            len("wrdata ") + len(file_stem) + len("_part999") + len(file_extension) + 1
        )

        chunks: List[List[str]] = []
        current_chunk: List[str] = []
        current_length = prefix_allowance

        for magnitude in magnitudes:
            magnitude_length = len(magnitude) + 1
            if (
                current_chunk
                and current_length + magnitude_length > self.MAX_WRDATA_LINE_LENGTH
            ):
                chunks.append(current_chunk)
                current_chunk = []
                current_length = prefix_allowance
            current_chunk.append(magnitude)
            current_length += magnitude_length

        if current_chunk:
            chunks.append(current_chunk)

        commands = []
        for index, chunk in enumerate(chunks):
            if index == 0:
                chunk_filename = export_filename
            else:
                chunk_filename = f"{file_stem}_part{index}{file_extension}"
            commands.append(f"wrdata {chunk_filename} {' '.join(chunk)}")

        return commands

    def write_circuit_file(self) -> None:
        """
        Writes the .cir circuit file to execute in Spice. The file is saved in simulation_results/model-name_simulations
        :return: None
        """
        self.directories_management_service.get_export_simulation_file_path()
        self.directories_management_service.create_simulation_results_for_model_folder_if_not_exists(
            self.subcircuit_file_service.model
        )

        with open(
            self.directories_management_service.get_circuit_file_path(), "w+"
        ) as f:
            f.write(
                f"* MEMRISTOR CIRCUIT - MODEL {self.subcircuit_file_service.model.value}"
            )
            self._write_dependencies(f)
            self._write_components(f)
            self._write_analysis_commands(f)
            self._write_control_commands(f)
            f.write("\nquit\n")
            f.write("\n.endc\n")
            f.write(".end\n")
