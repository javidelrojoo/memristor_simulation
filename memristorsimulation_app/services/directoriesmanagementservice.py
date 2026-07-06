import os

from memristorsimulation_app.constants import (
    SIMULATIONS_DIR,
    ModelsSimulationFolders,
    MemristorModels,
)
from memristorsimulation_app.representations import ExportParameters


class DirectoriesManagementService:
    def __init__(
        self,
        model: MemristorModels = None,
        export_parameters: ExportParameters = None,
    ):
        self.model = model
        self.export_parameters = export_parameters

    @staticmethod
    def create_simulation_results_for_model_folder_if_not_exists(
        model: MemristorModels,
    ):
        model_simulation_folder_ = (
            ModelsSimulationFolders.get_simulation_folder_by_model(model).value
        )
        # exist_ok=True evita la carrera cuando varias realizaciones en
        # paralelo intentan crear la misma carpeta a la vez.
        os.makedirs(f"{SIMULATIONS_DIR}/{model_simulation_folder_}", exist_ok=True)

    def create_simulation_parameter_folder_if_not_exist(
        self, model_simulation_folder: ModelsSimulationFolders
    ) -> None:
        folder_directory = f"{SIMULATIONS_DIR}/{model_simulation_folder.value}/{self.export_parameters.folder_name}"
        os.makedirs(folder_directory, exist_ok=True)

    def get_or_create_figures_directory(self) -> str:
        figures_dir_path = self.get_simulation_folder_path() + "/figures"
        os.makedirs(figures_dir_path, exist_ok=True)
        return figures_dir_path

    def get_circuit_file_path(self) -> str:
        return f"{SIMULATIONS_DIR}/{self.get_circuit_dir_and_file_name()}"

    def get_subcircuit_file_path(self) -> str:
        return f"{SIMULATIONS_DIR}/{self.get_subcircuit_dir_and_file_name()}"

    def get_export_simulation_file_path(self) -> str:
        self.create_simulation_parameter_folder_if_not_exist(
            self.export_parameters.model_simulation_folder
        )
        export_simulation_file_path = (
            f"{SIMULATIONS_DIR}/{self.export_parameters.model_simulation_folder.value}/"
            f"{self.export_parameters.folder_name}/{self.export_parameters.file_name}_results.csv"
        )

        return export_simulation_file_path

    def get_simulation_log_file_path(self) -> str:
        # El nombre del log usa solo el ultimo segmento del folder_name, ya que
        # en corridas multi-realizacion folder_name contiene subcarpetas (p. ej.
        # "test_123/seed_42") y no debe usarse completo como nombre de archivo.
        log_file_name = self.export_parameters.folder_name.split("/")[-1]
        return (
            f"{SIMULATIONS_DIR}/{self.export_parameters.model_simulation_folder.value}/"
            f"{self.export_parameters.folder_name}/{log_file_name}.log"
        )

    def get_circuit_dir_and_file_name(self) -> str:
        if self.model == MemristorModels.PERSHIN:
            return (
                f"{ModelsSimulationFolders.PERSHIN_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"pershin_circuit_file.cir"
            )
        elif self.model == MemristorModels.VOURKAS:
            return (
                f"{ModelsSimulationFolders.VOURKAS_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"vourkas_circuit_file.cir"
            )
        elif self.model == MemristorModels.BIOLEK:
            return (
                f"{ModelsSimulationFolders.BIOLEK_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"biolek_circuit_file.cir"
            )
        else:
            raise InvalidMemristorModel(f"The model {self.model} is not valid")

    def get_subcircuit_dir_and_file_name(self) -> str:
        if self.model == MemristorModels.PERSHIN:
            return (
                f"{ModelsSimulationFolders.PERSHIN_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"{self.model.value}"
            )
        elif self.model == MemristorModels.VOURKAS:
            return (
                f"{ModelsSimulationFolders.VOURKAS_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"{self.model.value}"
            )
        elif self.model == MemristorModels.BIOLEK:
            return (
                f"{ModelsSimulationFolders.BIOLEK_SIMULATIONS.value}/{self.export_parameters.folder_name}/"
                f"{self.model.value}"
            )
        else:
            raise InvalidMemristorModel(f"The model {self.model} is not valid")

    # TODO: Refactor dms, this method should have self.export_parameters or receive them as argument
    def get_simulation_folder_path(self) -> str:
        if not self.export_parameters:
            raise ValueError("Export parameters are not set")
        return f"{SIMULATIONS_DIR}/{self.export_parameters.model_simulation_folder.value}/{self.export_parameters.folder_name}"

    def get_all_simulation_files(self) -> list:
        files_to_include = []
        seen_paths = set()

        def add_file(file_path: str, archive_name: str) -> None:
            normalized_path = os.path.normcase(os.path.normpath(file_path))
            if normalized_path in seen_paths:
                return
            seen_paths.add(normalized_path)
            files_to_include.append((file_path, archive_name.replace(os.sep, "/")))

        subcircuit_path = self.get_subcircuit_file_path()
        if os.path.exists(subcircuit_path):
            add_file(subcircuit_path, os.path.basename(subcircuit_path))

        circuit_path = self.get_circuit_file_path()
        if os.path.exists(circuit_path):
            add_file(circuit_path, os.path.basename(circuit_path))

        export_path = self.get_export_simulation_file_path()
        if os.path.exists(export_path):
            add_file(export_path, os.path.basename(export_path))

        log_path = self.get_simulation_log_file_path()
        if os.path.exists(log_path):
            add_file(log_path, os.path.basename(log_path))

        plots_folder = self.get_or_create_figures_directory()
        if os.path.exists(plots_folder):
            for root, _, files in os.walk(plots_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(
                        file_path, self.get_simulation_folder_path()
                    )
                    add_file(file_path, relative_path)

        simulation_folder = self.get_simulation_folder_path()
        if os.path.exists(simulation_folder):
            for root, _, files in os.walk(simulation_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, simulation_folder)
                    add_file(file_path, relative_path)

        return files_to_include


class InvalidMemristorModel(Exception):
    pass
