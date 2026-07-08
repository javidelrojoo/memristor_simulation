import os

from memristorsimulation_app.constants import MemristorModels
from memristorsimulation_app.tests.basetestcase import BaseTestCase


class CircuitFileServiceTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

    def test_write_circuit_file_with_pershin_model(self):
        subcircuit_file_service = self.create_subcircuit_file_service(
            MemristorModels.PERSHIN
        )
        subcircuit_file_service.write_subcircuit_file()

        circuit_file_service = self.create_circuit_file_service(
            subcircuit_file_service=subcircuit_file_service
        )
        circuit_file_service.write_circuit_file()

        content = self.open_file(
            circuit_file_service.directories_management_service.get_circuit_file_path()
        )

        self.assertIn(
            f"* MEMRISTOR CIRCUIT - MODEL {MemristorModels.PERSHIN.value}",
            content,
        )

        # Dependencies (se usa solo el nombre de archivo para que NGSpice no
        # falle con rutas con espacios)
        self.assertIn(
            f".include {os.path.basename(circuit_file_service.directories_management_service.get_subcircuit_file_path())}",
            content,
        )

        # Components
        device = circuit_file_service.device_parameters[0].get_device()

        formatted_voltage_source = circuit_file_service.input_parameters.get_voltage_source_as_string().replace(
            "\n", ""
        )
        self.assertIn("* COMPONENTS:", content)
        self.assertIn(f"{formatted_voltage_source}", content)
        self.assertIn(f"{device}", content)

        # Analysis commands
        self.assertIn("* ANALYSIS COMMANDS:", content)
        self.assertIn(
            f"{circuit_file_service.simulation_parameters.get_analysis()}",
            content,
        )

        # Control commands
        self.assertIn("* CONTROL COMMANDS:", content)
        self.assertIn("run", content)
        self.assertIn("set wr_vecnames", content)
        self.assertIn("set wr_singlescale", content)
        # El CSV de resultados solo lleva la curva IV (time como escala,
        # vin, i(v1)); los estados internos van a un CSV separado.
        results_filename = os.path.basename(
            circuit_file_service.directories_management_service.get_export_simulation_file_path()
        )
        states_filename = os.path.basename(
            circuit_file_service.directories_management_service.get_export_states_file_path()
        )
        state_magnitudes = [
            magnitude
            for magnitude in circuit_file_service.directories_management_service.export_parameters.magnitudes
            if magnitude not in circuit_file_service.IV_MAGNITUDES
        ]
        self.assertIn(f"wrdata {results_filename} vin i(v1)", content)
        self.assertIn(
            f"wrdata {states_filename} {' '.join(state_magnitudes)}",
            content,
        )

        self.assertIn("quit", content)
        self.assertIn(".endc", content)
        self.assertIn(".end", content)
