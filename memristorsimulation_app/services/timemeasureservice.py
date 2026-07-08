import logging
import os
import re
import subprocess
import sys
import time

from dataclasses import asdict
from typing import List
from memristorsimulation_app.constants import TimeMeasures
from memristorsimulation_app.representations import TimeMeasure, AverageTimeMeasure
from memristorsimulation_app.services.directoriesmanagementservice import (
    DirectoriesManagementService,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TimeMeasureService:
    def __init__(self, directories_management_service: DirectoriesManagementService):
        self.directories_management_service = directories_management_service

        self.command_line = None
        self.circuit_file_path = (
            self.directories_management_service.get_circuit_file_path()
        )
        self.simulation_result_file_path = (
            self.directories_management_service.get_export_simulation_file_path()
        )
        self.simulation_states_file_path = (
            self.directories_management_service.get_export_states_file_path()
        )
        self.simulation_log_path = (
            self.directories_management_service.get_simulation_log_file_path()
        )
        self.execute_command = ""

    def execute_with_time_measure(
        self, enable_print_time_measure: bool = True
    ) -> TimeMeasure:
        time_measure = TimeMeasure(start_time=self.init_python_execution_time_measure())

        try:
            if self._is_os_linux():
                self.execute_command = f"time ngspice {self.circuit_file_path} 2>&1"

                if (
                    not self.circuit_file_path
                    or not self.simulation_result_file_path
                    or not self.simulation_log_path
                ):
                    raise FilePathNotFoundError(
                        f"File paths not provided for TimeMeasureService."
                    )

                logger.info(f"Executing command: {self.execute_command}")

                process = subprocess.Popen(
                    ["bash", "-c", self.execute_command, "_"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.dirname(self.circuit_file_path),
                    env=os.environ.copy(),
                )

                simulation_log, linux_time_output = process.communicate()

                if process.returncode != 0:
                    logger.error(
                        f"Simulation process failed with return code: {process.returncode}"
                    )
                else:
                    logger.info(f"Simulation process ended succesfully")

                self._log_ngspice_reported_errors(
                    simulation_log.decode(errors="replace")
                )
                self._merge_wrdata_part_files()

                time_measure = self.write_python_time_measure_into_csv(time_measure)
                self.write_linux_time_measure_into_csv(linux_time_output, time_measure)

            elif self._is_os_windows():
                # -b (batch) evita la ventana interactiva de ngspice y -o guarda
                # toda su salida (errores incluidos, ej. "singular matrix" o
                # "Timestep too small") en el log del seed. Sin esto, el ngspice
                # de Windows manda los mensajes a su propia consola, los pipes
                # llegan vacios y el log queda sin informacion util.
                # El log se pasa como nombre relativo porque ngspice corre con
                # cwd en la carpeta del seed: las rutas absolutas con espacios
                # y separadores mezclados ("\" y "/") hacen fallar el -o en
                # Windows con "No such file or directory".
                command = [
                    "ngspice",
                    "-b",
                    "-o",
                    os.path.basename(self.simulation_log_path),
                    self.circuit_file_path,
                ]
                logger.info(f"Executing command: {subprocess.list2cmdline(command)}")

                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.dirname(self.circuit_file_path),
                    env=os.environ.copy(),
                )

                stdout_output, stderr_output = process.communicate()
                simulation_log = stdout_output + stderr_output

                if process.returncode != 0:
                    logger.error(
                        f"Simulation process failed with return code: {process.returncode}"
                    )
                else:
                    logger.info(f"Simulation process ended succesfully")

                self._log_ngspice_reported_errors()
                self._merge_wrdata_part_files()

                time_measure = self.write_python_time_measure_into_csv(time_measure)

            else:
                raise OperatingSystemError()

        except Exception as e:
            logger.error(f"Error during time measurement execution: {str(e)}")
            raise e

        self.write_simulation_log(
            simulation_log=simulation_log.decode(), time_measure=time_measure
        )

        if enable_print_time_measure:
            self.print_time_measure(time_measure)

        return time_measure

    NGSPICE_ERROR_MARKERS = (
        "singular matrix",
        "timestep too small",
        "simulation(s) aborted",
        "no convergence",
        "fatal error",
    )

    def _log_ngspice_reported_errors(self, ngspice_output: str = None) -> None:
        """
        Scans the NGSpice output for known fatal messages and logs them, so
        failed runs are visible in the console instead of failing silently
        (NGSpice exits with code 0 even after aborting the transient).
        If no text is given, reads the seed log written by 'ngspice -b -o'.
        """
        if ngspice_output is None:
            if not self.simulation_log_path or not os.path.exists(
                self.simulation_log_path
            ):
                return
            with open(self.simulation_log_path, errors="replace") as f:
                ngspice_output = f.read()

        lowered_output = ngspice_output.lower()
        found_markers = [
            marker for marker in self.NGSPICE_ERROR_MARKERS if marker in lowered_output
        ]
        if found_markers:
            logger.error(
                f"NGSpice reported errors ({', '.join(found_markers)}) - "
                f"see {self.simulation_log_path}"
            )

    def _merge_wrdata_part_files(self) -> None:
        """
        Large networks need several wrdata commands (NGSpice truncates control
        lines longer than ~512 chars), each writing a *_part<N>.csv file.
        This merges those part files (dropping their duplicated time column)
        back into the base CSV and deletes them, so downstream code keeps
        working with a single file. Part files are generated for the states
        CSV (the results CSV only holds time, vin, i(v1) and never needs
        splitting), but the results CSV is also checked for backwards
        compatibility.
        """
        self._merge_wrdata_part_files_into(self.simulation_states_file_path)
        self._merge_wrdata_part_files_into(self.simulation_result_file_path)

    def _merge_wrdata_part_files_into(self, results_path: str) -> None:
        if not results_path or not os.path.exists(results_path):
            return

        directory = os.path.dirname(results_path)
        file_stem, file_extension = os.path.splitext(os.path.basename(results_path))
        part_pattern = re.compile(
            rf"^{re.escape(file_stem)}_part(\d+){re.escape(file_extension)}$"
        )

        part_files = sorted(
            (
                (int(match.group(1)), os.path.join(directory, file_name))
                for file_name in os.listdir(directory)
                if (match := part_pattern.match(file_name))
            ),
        )

        if not part_files:
            return

        with open(results_path) as f:
            merged_lines = f.read().splitlines()

        for part_number, part_path in part_files:
            with open(part_path) as f:
                part_lines = f.read().splitlines()

            if len(part_lines) != len(merged_lines):
                logger.error(
                    f"Cannot merge {part_path}: it has {len(part_lines)} lines but "
                    f"{results_path} has {len(merged_lines)}. Keeping it unmerged."
                )
                continue

            for index, part_line in enumerate(part_lines):
                # Drop the first column (duplicated time scale) of each part
                columns_without_time = part_line.split()[1:]
                merged_lines[index] = (
                    f"{merged_lines[index].rstrip()} {' '.join(columns_without_time)}"
                )

            os.remove(part_path)

        with open(results_path, "w") as f:
            f.write("\n".join(merged_lines) + "\n")

    @staticmethod
    def _is_os_windows() -> bool:
        return sys.platform == "win32"

    @staticmethod
    def init_python_execution_time_measure() -> float:
        return time.time()

    @staticmethod
    def end_python_execution_time_measure(start_time) -> float:
        return time.time() - start_time

    @staticmethod
    def _format_linux_time_output(
        decoded_linux_time_output: str, time_measure: TimeMeasure
    ) -> TimeMeasure:
        decoded_real_time = decoded_linux_time_output.split("\n")[1].replace(",", ".")
        decoded_user_time = decoded_linux_time_output.split("\n")[2].replace(",", ".")
        decoded_sys_time = decoded_linux_time_output.split("\n")[3].replace(",", ".")

        real_time_minutes = float(decoded_real_time.split("\t")[1].split("m")[0])
        real_time_seconds = float(
            decoded_real_time.split("\t")[1].split("m")[1].split("s")[0]
        )
        real_time_ms = (real_time_minutes * 60 + real_time_seconds) * 1000

        user_time_minutes = float(decoded_user_time.split("\t")[1].split("m")[0])
        user_time_seconds = float(
            decoded_user_time.split("\t")[1].split("m")[1].split("s")[0]
        )
        user_time_ms = (user_time_minutes * 60 + user_time_seconds) * 1000

        sys_time_minutes = float(decoded_sys_time.split("\t")[1].split("m")[0])
        sys_time_seconds = float(
            decoded_sys_time.split("\t")[1].split("m")[1].split("s")[0]
        )
        sys_time_ms = (sys_time_minutes * 60 + sys_time_seconds) * 1000

        time_measure.linux_real_execution_time = real_time_ms
        time_measure.linux_user_execution_time = user_time_ms
        time_measure.linux_sys_execution_time = sys_time_ms

        return time_measure

    @staticmethod
    def compute_time_average(
        time_measures: List[TimeMeasure], amount_iterations: int
    ) -> AverageTimeMeasure:
        average_python_execution_time = (
            sum(time_measure.python_execution_time for time_measure in time_measures)
            / amount_iterations
        )
        average_linux_real_execution_time = (
            sum(
                time_measure.linux_real_execution_time for time_measure in time_measures
            )
            / amount_iterations
        )
        average_linux_user_execution_time = (
            sum(
                time_measure.linux_user_execution_time for time_measure in time_measures
            )
            / amount_iterations
        )
        average_linux_sys_execution_time = (
            sum(time_measure.linux_sys_execution_time for time_measure in time_measures)
            / amount_iterations
        )

        return AverageTimeMeasure(
            amount_iterations,
            average_python_execution_time,
            average_linux_real_execution_time,
            average_linux_user_execution_time,
            average_linux_sys_execution_time,
        )

    def write_python_time_measure_into_csv(
        self, time_measure: TimeMeasure
    ) -> TimeMeasure:
        python_time_measure_ms = (
            self.end_python_execution_time_measure(time_measure.start_time)
        ) * 1000
        time_measure.python_execution_time = python_time_measure_ms

        with open(self.simulation_result_file_path, "a") as f:
            f.write(
                f"\n# {TimeMeasures.PYTHON_EXECUTION_TIME.value} = {python_time_measure_ms} ms"
            )

        return time_measure

    def write_linux_time_measure_into_csv(
        self, linux_time_output: bytes, time_measure: TimeMeasure
    ) -> None:
        formatted_time_measure = self._format_linux_time_output(
            linux_time_output.decode(), time_measure
        )

        with open(self.simulation_result_file_path, "a") as f:
            f.write(
                f"\n# {TimeMeasures.LINUX_REAL_EXECUTION_TIME.value} = "
                f"{formatted_time_measure.linux_real_execution_time} ms"
            )
            f.write(
                f"\n# {TimeMeasures.LINUX_USER_EXECUTION_TIME.value} = "
                f"{formatted_time_measure.linux_user_execution_time} ms"
            )
            f.write(
                f"\n# {TimeMeasures.LINUX_SYS_EXECUTION_TIME.value} = "
                f"{formatted_time_measure.linux_sys_execution_time} ms"
            )

    @staticmethod
    def print_time_measure(time_measure: TimeMeasure):
        print(f'\n{"#" * 30}')
        for k, v in asdict(time_measure).items():
            if k != "start_time" and v is not None:
                print(f"# {k} = {str(v)} ms")
        print(f"\n")

    @staticmethod
    def print_average_time_measure(average_time_measure: AverageTimeMeasure):
        print(f'\n{"#" * 30}')
        for k, v in asdict(average_time_measure).items():
            if k == "amount_iterations":
                print(f"# {k} = {str(v)}")
            elif k != "amount_iterations" and v is not None:
                print(f"# {k} = {str(v)} ms")
        print(f"\n")

    def write_simulation_log(
        self,
        simulation_log: str = None,
        time_measure: TimeMeasure = None,
        average_time_measure: AverageTimeMeasure = None,
    ) -> None:
        with open(f"{self.simulation_log_path}", "a+") as f:
            if simulation_log:
                f.write(f'{"#" * 60}\n{simulation_log}\n\n')

            if time_measure:
                for k, v in asdict(time_measure).items():
                    if k != "start_time" and v is not None:
                        f.write(f"# {k} = {str(v)} ms\n")
                f.write("\n")

            if average_time_measure:
                f.write(f'{"#" * 20}  AVERAGE TIME MEASURES  {"#" * 20}\n')
                for k, v in asdict(average_time_measure).items():
                    if k == "amount_iterations":
                        f.write(f"# {k} = {str(v)}\n")
                    elif v is not None:
                        f.write(f"# {k} = {str(v)} ms\n")
                f.write("\n")

    @staticmethod
    def _is_os_linux() -> bool:
        return sys.platform == "linux" or sys.platform == "linux2"


class FilePathNotFoundError(Exception):
    pass


class OperatingSystemError(Exception):
    pass
