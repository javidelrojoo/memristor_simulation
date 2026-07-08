import os

from unittest.mock import patch

from memristorsimulation_app.representations import SweepParameters
from memristorsimulation_app.serializers.simulation import SweepParametersSerializer
from memristorsimulation_app.services.simulationservice import SimulationService
from memristorsimulation_app.tests.basetestcase import BaseTestCase


class TestSweepParameters(BaseTestCase):
    def test_from_dict_none_is_not_sweep(self):
        sweep = SweepParameters.from_dict(None)

        self.assertFalse(sweep.is_sweep())

    def test_combinations_cross_product(self):
        sweep = SweepParameters(
            vt_values=[0.1, 0.2], ohmic_probability_values=[0.0, 0.5]
        )

        self.assertEqual(
            sweep.combinations(0.6, 0.0),
            [(0.1, 0.0), (0.1, 0.5), (0.2, 0.0), (0.2, 0.5)],
        )

    def test_combinations_uses_defaults_for_missing_parameter(self):
        sweep = SweepParameters(vt_values=[0.1, 0.2])

        self.assertEqual(sweep.combinations(0.6, 0.3), [(0.1, 0.3), (0.2, 0.3)])

        sweep = SweepParameters(ohmic_probability_values=[0.1])

        self.assertEqual(sweep.combinations(0.6, 0.3), [(0.6, 0.1)])


class TestSweepParametersSerializer(BaseTestCase):
    def test_valid_sweep(self):
        serializer = SweepParametersSerializer(
            data={"vt_values": [0.1, 0.2], "ohmic_probability_values": [0.0, 0.5]}
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_probability_out_of_range(self):
        serializer = SweepParametersSerializer(
            data={"ohmic_probability_values": [0.5, 1.5]}
        )

        self.assertFalse(serializer.is_valid())

    def test_rejects_too_many_combinations(self):
        serializer = SweepParametersSerializer(
            data={
                "vt_values": [i * 0.1 for i in range(15)],
                "ohmic_probability_values": [i * 0.05 for i in range(15)],
            }
        )

        self.assertFalse(serializer.is_valid())


class TestSimulationServiceSweep(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.request_parameters = {
            "model": "pershin.sub",
            "subcircuit": {
                "model_parameters": {
                    "alpha": 0.0,
                    "beta": 500000.0,
                    "rinit": 200000.0,
                    "roff": 200000.0,
                    "ron": 2000.0,
                    "vt": 0.6,
                },
                "name": "memristor",
                "nodes": ["pl", "mn", "x"],
            },
            "input_parameters": {
                "source_number": 1,
                "n_plus": "vin",
                "n_minus": "gnd",
                "wave_form": {
                    "type": "sin",
                    "parameters": {
                        "vo": 0.0,
                        "amplitude": 1.0,
                        "frequency": 1.0,
                    },
                },
            },
            "simulation_parameters": {
                "analysis_type": ".tran",
                "tstep": 2e-3,
                "tstop": 10,
                "uic": True,
            },
            "export_parameters": {
                "model_simulation_folder": "pershin_simulations",
                "folder_name": "sweep_test",
                "file_name": "sweep_results",
                "magnitudes": ["vin", "i(v1)"],
            },
            "network_type": "GRID_2D_GRAPH",
            "network_parameters": {"n": 4, "m": 4, "seed": 42},
            "ohmic_junction_parameters": {
                "probability": 0.0,
                "resistance": 8.5e-3,
                "seed": 7,
                "amount_realizations": 1,
            },
            "sweep_parameters": {
                "vt_values": [0.1, 0.2],
                "ohmic_probability_values": [0.0, 0.5],
            },
            "amount_iterations": 1,
            "plot_types": ["IV"],
        }

    def test_simulate_sweep_runs_every_combination(self):
        service = SimulationService(self.request_parameters)
        base_folder_name = service.simulation_inputs.export_parameters.folder_name

        child_services = []

        def fake_simulate(child_self):
            child_services.append(child_self)

        with patch.object(
            SimulationService, "simulate", autospec=True, side_effect=fake_simulate
        ):
            service._simulate_sweep()

        self.assertEqual(len(child_services), 4)

        expected_combinations = [(0.1, 0.0), (0.1, 0.5), (0.2, 0.0), (0.2, 0.5)]
        for child, (vt, probability) in zip(child_services, expected_combinations):
            self.assertEqual(
                child.simulation_inputs.subcircuit.model_parameters.vt, vt
            )
            self.assertEqual(
                child.simulation_inputs.ohmic_junction_parameters.probability,
                probability,
            )
            self.assertEqual(
                child.simulation_inputs.export_parameters.folder_name,
                f"{base_folder_name}/vt_{vt:g}_p_{probability:g}",
            )
            # Los hijos no deben barrer de nuevo
            self.assertFalse(child.simulation_inputs.sweep_parameters.is_sweep())
            # Comparten la topología de red del padre
            self.assertIs(child._network_service, service._network_service)

        summary_path = os.path.join(
            service.directories_management_service.get_simulation_folder_path(),
            "sweep_summary.csv",
        )
        self.assertTrue(os.path.exists(summary_path))

        with open(summary_path) as summary_file:
            lines = summary_file.read().strip().splitlines()
        self.assertEqual(len(lines), 5)  # header + 4 combinaciones

    def test_simulate_dispatches_to_sweep(self):
        service = SimulationService(self.request_parameters)

        with patch.object(SimulationService, "_simulate_sweep") as mock_sweep:
            service.simulate()

        mock_sweep.assert_called_once()

    def test_simulate_without_sweep_does_not_dispatch(self):
        self.request_parameters.pop("sweep_parameters")
        service = SimulationService(self.request_parameters)

        with patch.object(
            SimulationService, "_simulate_sweep"
        ) as mock_sweep, patch.object(
            SimulationService, "_run_realization"
        ) as mock_run:
            service.simulate()

        mock_sweep.assert_not_called()
        mock_run.assert_called_once()
