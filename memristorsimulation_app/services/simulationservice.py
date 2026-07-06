import copy
import csv
import os
import random
import threading
import zipfile

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from memristorsimulation_app.constants import (
    SIMULATIONS_DIR,
    MemristorModels,
    NetworkType,
)
from memristorsimulation_app.representations import (
    ExportParameters,
    InputParameters,
    NetworkParameters,
    SimulationInputs,
    SimulationParameters,
    Subcircuit,
    OhmicJunctionParameters,
)
from memristorsimulation_app.services.circuitfileservice import CircuitFileService
from memristorsimulation_app.services.directoriesmanagementservice import (
    DirectoriesManagementService,
)
from memristorsimulation_app.services.networkservice import NetworkService
from memristorsimulation_app.services.ngspiceservice import NGSpiceService
from memristorsimulation_app.services.plotterservice import PlotterService
from memristorsimulation_app.services.subcircuitfileservice import SubcircuitFileService
from memristorsimulation_app.simulation_templates.basetemplate import BaseTemplate


class SimulationService(BaseTemplate):
    # Maximo de procesos ngspice corriendo en simultaneo cuando hay varias
    # realizaciones. Limitado por RAM/nucleos de la maquina (ver discusion:
    # Ryzen 7 5825U, 8 nucleos, RAM como limite practico).
    MAX_PARALLEL_REALIZATIONS = 5

    def __init__(self, request_parameters: dict):
        self.request_parameters = request_parameters
        self.simulation_inputs: SimulationInputs = self.parse_request_parameters(
            request_parameters
        )

        self.directories_management_service = DirectoriesManagementService(
            self.simulation_inputs.model, self.simulation_inputs.export_parameters
        )
        self._network_service = None
        # matplotlib/pyplot no es thread-safe: serializa el ploteo entre
        # realizaciones paralelas.
        self._plot_lock = threading.Lock()
        # generate_device_parameters muta estado interno del NetworkService
        # compartido: serializa su uso entre realizaciones paralelas.
        self._network_lock = threading.Lock()

    def parse_request_parameters(self, request_parameters: dict) -> SimulationInputs:
        model = MemristorModels(request_parameters["model"])
        export_params = ExportParameters.from_dict(
            request_parameters["export_parameters"], model
        )
        input_params = InputParameters.from_dict(request_parameters["input_parameters"])
        simulation_params = SimulationParameters.from_dict(
            request_parameters["simulation_parameters"]
        )
        subcircuit = Subcircuit.from_dict(request_parameters["subcircuit"])
        network_type = NetworkType(request_parameters["network_type"])
        
        # Safe extraction for network parameters
        network_params_dict = request_parameters.get("network_parameters", {})
        network_params = NetworkParameters(**network_params_dict)
        
        plot_types = request_parameters.get("plot_types", [])
        graphml_content = request_parameters.get("graphml_content", None)
        ohmic_junction_params = OhmicJunctionParameters.from_dict(
            request_parameters.get("ohmic_junction_parameters")
        )
        force_save_states = bool(request_parameters.get("force_save_states", False))

        return SimulationInputs(
            model=model,
            subcircuit=subcircuit,
            input_parameters=input_params,
            simulation_parameters=simulation_params,
            export_parameters=export_params,
            network_type=network_type,
            network_parameters=network_params,
            plot_types=plot_types,
            graphml_content=graphml_content,
            ohmic_junction_parameters=ohmic_junction_params,
            force_save_states=force_save_states,
        )

    def create_subcircuit_file_service_from_request(
        self, directories_management_service: DirectoriesManagementService = None
    ) -> SubcircuitFileService:
        # Sources, components, dependencies and control_cmd are created by default due to its complexity and impact in the subcircuit
        directories_management_service = (
            directories_management_service or self.directories_management_service
        )
        default_sources = self.create_default_behavioural_source()
        default_components, model_dependencies = (
            self.create_default_components_and_dependencies_from_model(
                self.simulation_inputs.model
            )
        )
        default_control_cmd = self.create_default_control_cmd()

        return SubcircuitFileService(
            model=self.simulation_inputs.model,
            subcircuit=self.simulation_inputs.subcircuit,
            sources=default_sources,
            directories_management_service=directories_management_service,
            model_dependencies=model_dependencies,
            components=default_components,
            control_commands=[default_control_cmd],
        )

    def _get_or_create_network_service(self):
        """
        Crea el NetworkService una sola vez y lo reutiliza. Esto garantiza que
        todas las realizaciones compartan exactamente la misma topología de red
        y que solo cambie la asignación de junturas óhmicas entre realizaciones.
        """
        if self._network_service is not None:
            return self._network_service

        if self.simulation_inputs.network_type == NetworkType.GRAPHML_UPLOAD:
            # Use the class method you created, completely avoiding the standard __init__
            self._network_service = NetworkService.from_graphml(
                graphml_content=self.simulation_inputs.graphml_content
            )
        elif self.simulation_inputs.network_type != NetworkType.SINGLE_DEVICE:
            self._network_service = NetworkService(
                self.simulation_inputs.network_type,
                self.simulation_inputs.network_parameters,
            )

        return self._network_service

    def create_circuit_file_service_from_request(
        self,
        subcircuit_file_services: SubcircuitFileService,
        ohmic_rng: random.Random = None,
        export_parameters: ExportParameters = None,
        directories_management_service: DirectoriesManagementService = None,
    ) -> CircuitFileService:
        export_parameters = (
            export_parameters or self.simulation_inputs.export_parameters
        )
        directories_management_service = (
            directories_management_service or self.directories_management_service
        )
        network_service, ignore_states = None, None

        if self.simulation_inputs.network_type != NetworkType.SINGLE_DEVICE:
            network_service = self._get_or_create_network_service()
            ignore_states = network_service.should_ignore_states()

        if self.simulation_inputs.force_save_states:
            ignore_states = False

        # El NetworkService es compartido entre realizaciones y
        # generate_device_parameters muta su estado interno (connections),
        # por eso se serializa con un lock al correr en paralelo.
        with self._network_lock:
            device_params = self.create_device_parameters(
                self.simulation_inputs.network_type,
                network_service=network_service,
                ohmic_probability=self.simulation_inputs.ohmic_junction_parameters.probability,
                ohmic_resistance=self.simulation_inputs.ohmic_junction_parameters.resistance,
                rng=ohmic_rng,
                )

        if self.simulation_inputs.force_save_states and device_params:
            state_nodes = [
                device_param.nodes[2]
                for device_param in device_params
                if device_param.ohmic_resistance is None  # los óhmicos no tienen estado memristivo
            ]
            existing = set(export_parameters.magnitudes)
            for node in state_nodes:
                if node not in existing:
                    export_parameters.magnitudes.append(node)
                    existing.add(node)

        return CircuitFileService(
            subcircuit_file_services,
            self.simulation_inputs.input_parameters,
            device_params,
            self.simulation_inputs.simulation_parameters,
            directories_management_service,
            ignore_states=ignore_states,
        )

    def _build_from_request_and_write(
        self,
        ohmic_rng: random.Random = None,
        export_parameters: ExportParameters = None,
        directories_management_service: DirectoriesManagementService = None,
    ) -> CircuitFileService:
        subcircuit_file_service = self.create_subcircuit_file_service_from_request(
            directories_management_service=directories_management_service
        )
        circuit_file_service = self.create_circuit_file_service_from_request(
            subcircuit_file_service,
            ohmic_rng=ohmic_rng,
            export_parameters=export_parameters,
            directories_management_service=directories_management_service,
        )
        subcircuit_file_service.write_subcircuit_file()
        circuit_file_service.write_circuit_file()

        return circuit_file_service

    def _run_realization(
        self,
        ohmic_rng: random.Random = None,
        export_parameters: ExportParameters = None,
        directories_management_service: DirectoriesManagementService = None,
    ) -> CircuitFileService:
        export_parameters = (
            export_parameters or self.simulation_inputs.export_parameters
        )
        directories_management_service = (
            directories_management_service or self.directories_management_service
        )
        circuit_file_service = self._build_from_request_and_write(
            ohmic_rng=ohmic_rng,
            export_parameters=export_parameters,
            directories_management_service=directories_management_service,
        )
        ngspice_service = NGSpiceService(directories_management_service)
        ngspice_service.run_single_circuit_simulation(
            self.simulation_inputs.amount_iterations
        )
        # pyplot usa estado global (no thread-safe): una sola realizacion
        # plotea a la vez. ngspice, que domina el tiempo, sigue en paralelo.
        with self._plot_lock:
            self.plot(
                export_parameters=export_parameters,
                model_parameters=circuit_file_service.subcircuit_file_service.subcircuit.model_parameters,
                input_parameters=circuit_file_service.input_parameters,
                plot_types=self.simulation_inputs.plot_types,
            )
        return circuit_file_service

    def simulate(self) -> None:
        ohmic_params = self.simulation_inputs.ohmic_junction_parameters
        amount_realizations = max(1, ohmic_params.amount_realizations or 1)

        if amount_realizations == 1:
            ohmic_rng = (
                random.Random(ohmic_params.seed)
                if ohmic_params.seed is not None
                else None
            )
            self._run_realization(ohmic_rng=ohmic_rng)
            return

        self._simulate_multiple_realizations(amount_realizations)

    def _simulate_multiple_realizations(self, amount_realizations: int) -> None:
        """
        Ejecuta varias realizaciones de la simulación manteniendo fija la
        topología de red y variando la semilla de asignación de junturas
        óhmicas. Cada realización se guarda en una subcarpeta seed_<semilla>
        y al final se escribe un CSV resumen para el análisis estadístico.

        Las realizaciones corren en paralelo (hasta MAX_PARALLEL_REALIZATIONS
        procesos ngspice simultáneos). Cada realización usa sus propios
        ExportParameters y DirectoriesManagementService, por lo que escribe
        en su propia carpeta seed_<semilla> sin pisarse con las demás.
        """
        ohmic_params = self.simulation_inputs.ohmic_junction_parameters
        base_export = self.simulation_inputs.export_parameters
        base_folder_name = base_export.folder_name
        base_seed = (
            ohmic_params.seed
            if ohmic_params.seed is not None
            else random.randrange(0, 2**31)
        )

        # Crea la topologia de red UNA sola vez antes de lanzar los threads,
        # para que no la construyan dos realizaciones a la vez.
        if self.simulation_inputs.network_type != NetworkType.SINGLE_DEVICE:
            self._get_or_create_network_service()

        def run_one(realization_index: int):
            seed = base_seed + realization_index

            realization_export = copy.copy(base_export)
            realization_export.folder_name = f"{base_folder_name}/seed_{seed}"
            realization_export.magnitudes = list(base_export.magnitudes)

            realization_dms = DirectoriesManagementService(
                self.simulation_inputs.model, realization_export
            )

            circuit_file_service = self._run_realization(
                ohmic_rng=random.Random(seed),
                export_parameters=realization_export,
                directories_management_service=realization_dms,
            )
            return seed, realization_export, circuit_file_service

        max_workers = min(self.MAX_PARALLEL_REALIZATIONS, amount_realizations)
        results = [None] * amount_realizations
        errors = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_one, realization_index): realization_index
                for realization_index in range(amount_realizations)
            }
            for future in as_completed(futures):
                realization_index = futures[future]
                try:
                    results[realization_index] = future.result()
                except Exception as error:
                    errors.append((realization_index, error))

        if errors:
            errors.sort(key=lambda item: item[0])
            raise errors[0][1]

        summary_rows = []
        for realization_index, (seed, realization_export, circuit_file_service) in (
            enumerate(results)
        ):
            device_parameters = circuit_file_service.device_parameters or []
            ohmic_devices = sum(
                1
                for device in device_parameters
                if device.ohmic_resistance is not None
            )
            summary_rows.append(
                {
                    "realization": realization_index + 1,
                    "seed": seed,
                    "folder": f"seed_{seed}",
                    "ohmic_probability": ohmic_params.probability,
                    "total_devices": len(device_parameters),
                    "ohmic_devices": ohmic_devices,
                    "memristive_devices": len(device_parameters) - ohmic_devices,
                    "results_csv": f"seed_{seed}/{realization_export.file_name}_results.csv",
                }
            )

        self._write_realizations_summary(summary_rows)
        self._plot_realizations_summary(summary_rows)

    def _plot_realizations_summary(self, summary_rows: list) -> None:
        """
        Genera la figura resumen (promedio ± desviación estándar de la
        corriente) a partir de los CSV de resultados de cada realización.
        """
        if len(summary_rows) < 2:
            return

        base_folder = self.directories_management_service.get_simulation_folder_path()

        realization_dataframes = []
        for row in summary_rows:
            csv_path = os.path.join(base_folder, *row["results_csv"].split("/"))
            if not os.path.exists(csv_path):
                continue
            try:
                realization_dataframes.append(
                    PlotterService.read_results_dataframe(csv_path)
                )
            except Exception:
                continue

        if len(realization_dataframes) < 2:
            return

        plotter_service = PlotterService(
            simulation_results_directory_path=SIMULATIONS_DIR,
            export_parameters=self.simulation_inputs.export_parameters,
        )
        plotter_service.plot_realizations_summary(
            realization_dataframes,
            seeds=[row["seed"] for row in summary_rows],
            ohmic_probability=self.simulation_inputs.ohmic_junction_parameters.probability,
        )

    def _write_realizations_summary(self, summary_rows: list) -> None:
        if not summary_rows:
            return

        base_folder = self.directories_management_service.get_simulation_folder_path()
        os.makedirs(base_folder, exist_ok=True)
        summary_file_path = os.path.join(base_folder, "realizations_summary.csv")

        with open(summary_file_path, "w", newline="") as summary_file:
            writer = csv.DictWriter(summary_file, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

    def create_results_zip(self) -> BytesIO:
        zip_buffer = BytesIO()

        file_paths = self.directories_management_service.get_all_simulation_files()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path, archive_name in file_paths:
                if os.path.exists(file_path):
                    zip_file.write(file_path, archive_name)

        zip_buffer.seek(0)

        return zip_buffer

    def simulate_and_create_results_zip(self) -> BytesIO:
        self.simulate()

        return self.create_results_zip()
