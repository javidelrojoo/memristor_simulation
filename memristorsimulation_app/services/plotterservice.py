import os

import networkx as nx
import pandas as pd

import matplotlib
matplotlib.use('Agg')  # Add this line to use the non-interactive backend

from matplotlib import pyplot as plt
from matplotlib import animation as anime
from typing import List
from networkx import NetworkXError
from memristorsimulation_app.constants import MeasuredMagnitude
from memristorsimulation_app.representations import (
    DataLoader,
    ModelParameters,
    InputParameters,
    ExportParameters,
    Graph,
)
from memristorsimulation_app.services.directoriesmanagementservice import (
    DirectoriesManagementService,
)


class PlotterService:
    def __init__(
        self,
        simulation_results_directory_path: str,
        export_parameters: ExportParameters,
        model_parameters: ModelParameters = None,
        input_parameters: InputParameters = None,
        graph: Graph = None,
    ):
        self.simulation_results_directory_path = simulation_results_directory_path
        self.export_parameters = export_parameters
        self.model_simulations_directory_path = (
            f"{self.simulation_results_directory_path}/"
            f"{self.export_parameters.model_simulation_folder.value}"
        )
        self.simulations_directory_path = (
            f"{self.model_simulations_directory_path}/"
            f"{self.export_parameters.folder_name}"
        )
        self.figures_directory_path = f"{self.simulations_directory_path}/figures"
        self.directories_management_service = DirectoriesManagementService(
            export_parameters=self.export_parameters
        )
        self.directories_management_service.get_or_create_figures_directory()

        self.model_parameters = model_parameters
        self.input_parameters = input_parameters
        self.graph = graph

    @staticmethod
    def _get_csv_measured_magnitude(csv_file_name_no_extension: str):
        if csv_file_name_no_extension.endswith("_iv"):
            return MeasuredMagnitude.IV
        elif csv_file_name_no_extension.endswith("_states"):
            return MeasuredMagnitude.STATES
        else:
            return MeasuredMagnitude.OTHER

    def load_data_from_csv(self) -> List[DataLoader]:
        data_loaders = []
        files_in_model_simulations_directory = os.listdir(
            self.simulations_directory_path
        )

        for file_in_simulations_directory in sorted(
            files_in_model_simulations_directory
        ):
            if (
                file_in_simulations_directory.split(".csv")[0]
                == f"{self.export_parameters.file_name}_results"
            ):
                csv_file_name_no_extension = file_in_simulations_directory.replace(
                    ".csv", ""
                )
                csv_file_path = os.path.join(
                    self.simulations_directory_path, file_in_simulations_directory
                )
                dataframe = pd.DataFrame(
                    pd.read_csv(
                        csv_file_path, sep=r"\s+", engine="python", skipfooter=4
                    )
                )

                # Forcefully rename columns based on their index to guarantee
                # compatibility with all plotting functions (time, vin, current, state)
                rename_mapping = {}

                if len(dataframe.columns) > 0:
                    rename_mapping[dataframe.columns[0]] = "time"
                if len(dataframe.columns) > 1:
                    rename_mapping[dataframe.columns[1]] = "vin"
                if len(dataframe.columns) > 2:
                    rename_mapping[dataframe.columns[2]] = "i(v1)"
                if len(dataframe.columns) > 3:
                    rename_mapping[dataframe.columns[3]] = "l0"

                dataframe.rename(columns=rename_mapping, inplace=True)

                dataframe = self._append_states_columns(dataframe)

                data_loaders.append(DataLoader(dataframe, csv_file_name_no_extension))

        return data_loaders

    def _append_states_columns(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        """
        Los estados internos se guardan en un CSV separado
        (<file_name>_states.csv, con el tiempo como referencia) para que el
        *_results.csv quede liviano. Si ese archivo existe, se agregan sus
        columnas de estado al dataframe de resultados para que los plots de
        estados sigan funcionando igual que cuando todo estaba en un CSV.
        """
        states_file_path = os.path.join(
            self.simulations_directory_path,
            f"{self.export_parameters.file_name}_states.csv",
        )
        if "l0" in dataframe.columns or not os.path.exists(states_file_path):
            # Formato viejo (estados ya incluidos) o simulacion sin estados.
            return dataframe

        states_dataframe = pd.DataFrame(
            pd.read_csv(states_file_path, sep=r"\s+", engine="python")
        )
        if len(states_dataframe.columns) < 2:
            return dataframe

        # La primera columna es el tiempo (duplicado como referencia): se
        # descarta y las columnas de estado se agregan por posicion, ya que
        # ambos CSV provienen de la misma corrida de NGSpice.
        states_dataframe = states_dataframe.iloc[: len(dataframe), 1:]
        states_dataframe.rename(
            columns={states_dataframe.columns[0]: "l0"}, inplace=True
        )

        return pd.concat(
            [
                dataframe.reset_index(drop=True),
                states_dataframe.reset_index(drop=True),
            ],
            axis=1,
        )

    @staticmethod
    def read_results_dataframe(csv_file_path: str) -> pd.DataFrame:
        """
        Lee un CSV de resultados de NGSpice y normaliza los nombres de columnas
        (time, vin, i(v1), ...) con la misma logica que load_data_from_csv.
        """
        dataframe = pd.DataFrame(
            pd.read_csv(csv_file_path, sep=r"\s+", engine="python", skipfooter=4)
        )

        rename_mapping = {}
        if len(dataframe.columns) > 0:
            rename_mapping[dataframe.columns[0]] = "time"
        if len(dataframe.columns) > 1:
            rename_mapping[dataframe.columns[1]] = "vin"
        if len(dataframe.columns) > 2:
            rename_mapping[dataframe.columns[2]] = "i(v1)"
        if len(dataframe.columns) > 3:
            rename_mapping[dataframe.columns[3]] = "l0"
        dataframe.rename(columns=rename_mapping, inplace=True)

        # Descartar filas no numericas (footers/headers repetidos de NGSpice),
        # exigiendo validez solo en las columnas clave para no perder filas por
        # columnas de estado incompletas.
        key_columns = [c for c in ("time", "vin", "i(v1)") if c in dataframe.columns]
        dataframe = dataframe.apply(pd.to_numeric, errors="coerce").dropna(
            subset=key_columns
        )
        dataframe.reset_index(drop=True, inplace=True)

        return dataframe

    def plot_realizations_summary(
        self,
        realization_dataframes: List[pd.DataFrame],
        seeds: List[int] = None,
        ohmic_probability: float = None,
    ) -> None:
        """
        Figura resumen de multiples realizaciones: linea = promedio de la
        corriente entre realizaciones, contorno sombreado = +/- 1 desviacion
        estandar. Cada realizacion se interpola a una grilla temporal comun
        porque NGSpice puede devolver pasos de tiempo distintos en cada corrida.
        """
        import numpy as np

        valid_dataframes = [
            df
            for df in realization_dataframes
            if df is not None
            and "time" in df.columns
            and "i(v1)" in df.columns
            and len(df) >= 2  # descartar resultados vacios o corruptos
        ]
        if len(valid_dataframes) < 2:
            return

        reference = valid_dataframes[0]
        time_grid = reference["time"].to_numpy(dtype=float)

        currents = []
        for df in valid_dataframes:
            time_values = df["time"].to_numpy(dtype=float)
            current_values = df["i(v1)"].to_numpy(dtype=float)
            currents.append(np.interp(time_grid, time_values, current_values))

        currents = np.vstack(currents)
        mean_current = currents.mean(axis=0)
        std_current = currents.std(axis=0)

        amount = len(valid_dataframes)
        subtitle_parts = [f"N={amount} realizaciones"]
        if ohmic_probability is not None:
            subtitle_parts.append(f"p_ohmica={ohmic_probability}")
        if seeds:
            subtitle_parts.append(f"semillas={seeds[0]}..{seeds[-1]}")

        vin_grid = reference["vin"].to_numpy(dtype=float)

        plt.figure(figsize=(18, 8))

        # Columna izquierda: series temporales
        plt.subplot(2, 2, 1)
        plt.plot(time_grid, vin_grid)
        plt.xticks([])
        plt.ylabel("Vin [V]")

        plt.subplot(2, 2, 3)
        plt.fill_between(
            time_grid,
            mean_current - std_current,
            mean_current + std_current,
            alpha=0.3,
            label="±1σ",
        )
        plt.plot(time_grid, mean_current, label="promedio")
        plt.xlabel("Time [seg]")
        plt.ylabel("I(t) [A]")
        plt.legend(loc="best")

        # Columna derecha: curva I-V promedio con banda ±1σ. Como Vin barre
        # ida y vuelta (histeresis), el relleno se hace por tramos monotonos
        # para evitar artefactos de fill_between con x no monotono.
        plt.subplot(1, 2, 2)
        direction_changes = np.where(np.diff(np.sign(np.diff(vin_grid))) != 0)[0] + 1
        segment_bounds = [0] + direction_changes.tolist() + [len(vin_grid) - 1]
        for segment_index in range(len(segment_bounds) - 1):
            start = segment_bounds[segment_index]
            stop = segment_bounds[segment_index + 1] + 1
            plt.fill_between(
                vin_grid[start:stop],
                (mean_current - std_current)[start:stop],
                (mean_current + std_current)[start:stop],
                alpha=0.3,
                color="tab:blue",
                linewidth=0,
                label="±1σ" if segment_index == 0 else None,
            )
        plt.plot(vin_grid, mean_current, color="tab:blue", label="promedio")
        plt.xlabel("Vin [V]")
        plt.ylabel("I [A]")
        plt.title("I-V")
        plt.legend(loc="best")

        plt.suptitle(
            f"Corriente promedio ± desviación estándar\n{' | '.join(subtitle_parts)}",
            fontsize=18,
        )
        plt.savefig(f"{self.figures_directory_path}/realizations_mean_std.jpg")
        plt.close()

    def plot_iv(self, df: pd.DataFrame, csv_file_name: str, title: str = None) -> None:
        plt.figure(figsize=(12, 8))
        plt.plot(
            df["vin"],
            -df["i(v1)"],
            label=(
                f"{self.model_parameters.get_parameters_as_string()}"
                f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
            ),
        )
        plt.xlabel("Vin [V]")
        plt.ylabel("i(v1) [A]")
        plt.title(
            f'I-V {csv_file_name} {title if title is not None else ""}', fontsize=22
        )
        plt.autoscale()
        plt.legend(loc="lower right", fontsize=12)
        plt.savefig(f"{self.figures_directory_path}/{csv_file_name}_iv.jpg")
        plt.close()

    def plot_iv_overlapped(
        self, df: pd.DataFrame, title: str = None, label: str = None
    ) -> None:
        plt.figure(0, figsize=(12, 8))
        plt.plot(
            df["vin"],
            -df["i(v1)"],
            label=(
                label
                if label is not None
                else (
                    f"{self.model_parameters.get_parameters_as_string()}"
                    f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
                )
            ),
        )
        plt.xlabel("Vin [V]")
        plt.ylabel("i(v1) [A]")
        plt.title(f'I-V {title if title is not None else ""}', fontsize=22)
        plt.autoscale()
        plt.legend(loc="lower right", fontsize=12)
        plt.savefig(f"{self.figures_directory_path}/iv_overlapped.jpg")

    @staticmethod
    def _filter_zero_values_from_dataframe(
        df: pd.DataFrame, epsilon: float
    ) -> pd.DataFrame:
        df_filtered = df.dropna(subset=["i(v1)"])
        return df_filtered[abs(df_filtered["i(v1)"]) > epsilon]

    def plot_iv_log(
        self, df: pd.DataFrame, csv_file_name: str, title: str = None
    ) -> None:
        plt.figure(figsize=(12, 8))
        df_filtered = self._filter_zero_values_from_dataframe(df, 1e-7)
        plt.plot(
            df_filtered["vin"],
            abs(-df_filtered["i(v1)"]),
            label=(
                f"{self.model_parameters.get_parameters_as_string()}"
                f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
            ),
        )
        plt.yscale(value="log")
        plt.xlabel("Vin [V]")
        plt.ylabel("log(i(v1)) [A]")
        plt.title(
            f'log(I)-V {csv_file_name} {title if title is not None else ""}',
            fontsize=22,
        )
        plt.autoscale()
        plt.legend(loc="lower right", fontsize=12)
        plt.savefig(f"{self.figures_directory_path}/{csv_file_name}_log(i)v.jpg")
        plt.close()

    def plot_iv_log_overlapped(
        self, df: pd.DataFrame, title: str = None, label: str = None
    ):
        plt.figure(1, figsize=(12, 8))
        df_filtered = self._filter_zero_values_from_dataframe(df, 1e-7)
        plt.plot(
            df_filtered["vin"],
            abs(-df_filtered["i(v1)"]),
            label=(
                label
                if label is not None
                else (
                    f"{self.model_parameters.get_parameters_as_string()}"
                    f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
                )
            ),
        )
        plt.yscale(value="log")
        plt.xlabel("Vin [V]")
        plt.ylabel("log(i(v1)) [A]")
        plt.title(f'log(I)-V {title if title is not None else ""}', fontsize=22)
        plt.autoscale()
        plt.legend(loc="lower right", fontsize=12)
        plt.savefig(f"{self.figures_directory_path}/iv_log_overlapped.jpg")

    def plot_current_and_vin_vs_time(
        self, df: pd.DataFrame, csv_file_name: str, title: dict = None
    ) -> None:
        plt.figure(figsize=(12, 8))
        plt.subplot(2, 1, 1)
        plt.plot(df["time"], df["vin"])
        plt.xticks([])
        plt.ylabel("Vin [V]")
        plt.subplot(2, 1, 2)
        plt.plot(
            df["time"],
            df["i(v1)"],
            label=(
                f"{self.model_parameters.get_parameters_as_string()}"
                f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
            ),
        )
        plt.xlabel("Time [seg]")
        plt.ylabel(f"I(t) [A]")
        plt.suptitle(
            f'Input voltage and Source Current vs Time - {csv_file_name} {title if title is not None else ""}',
            fontsize=22,
        )
        plt.legend(loc="center", bbox_to_anchor=(0.5, 1.1))
        plt.savefig(f"{self.figures_directory_path}/{csv_file_name}_ivtime.jpg")
        plt.close()

    def plot_state_and_vin_vs_time(
        self, df: pd.DataFrame, csv_file_name: str, title: dict = None
    ) -> None:
        plt.figure(figsize=(12, 8))
        plt.subplot(2, 1, 1)
        plt.plot(df["time"], df["vin"])
        plt.xticks([])
        plt.ylabel("Vin [V]")
        plt.subplot(2, 1, 2)
        plt.plot(
            df["time"],
            df["l0"],
            label=(
                f"{self.model_parameters.get_parameters_as_string()}"
                f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
            ),
        )
        plt.xlabel("Time [seg]")
        plt.ylabel(f"l0 [ohm]")
        plt.suptitle(
            f'Input voltage and State vs Time - {csv_file_name} {title if title is not None else ""}',
            fontsize=22,
        )
        plt.legend(loc="center", bbox_to_anchor=(0.5, 1.1))
        plt.savefig(f"{self.figures_directory_path}/{csv_file_name}_statevtime.jpg")
        plt.close()

    def plot_states_overlapped(
        self, df: pd.DataFrame, title: str = None, label: str = None
    ) -> None:
        plt.figure(2, figsize=(12, 8))
        plt.plot(
            df["vin"],
            df["l0"],
            label=(
                label
                if label is not None
                else (
                    f"{self.model_parameters.get_parameters_as_string()}"
                    f"\n{self.input_parameters.get_input_parameters_for_plot_as_string()}"
                )
            ),
        )
        plt.xlabel("Vin [V]")
        plt.ylabel("l0 [ohm]")
        plt.title(
            f'Memristive states vs Input Voltage {title if title is not None else ""}',
            fontsize=22,
        )
        plt.autoscale()
        plt.legend(loc="center")
        plt.savefig(f"{self.figures_directory_path}/states_overlapped.jpg")

    def plot_iv_animated(
        self, df: pd.DataFrame, csv_file_name: str, title: dict = None
    ) -> None:
        fig = plt.figure(figsize=(12, 8))
        (l,) = plt.plot([], [], "k-")
        (p1,) = plt.plot([], [], "ko")
        plt.xlabel("Vin [V]")
        plt.ylabel("i(v1) [A]")
        plt.title(f"I-V {csv_file_name} - {title}", fontsize=10)

        plt.xlim(min(df["vin"]) * 1.1, max(df["vin"]) * 1.1)
        plt.ylim(min(df["i(v1)"]) * 1.1, max(df["i(v1)"]) * 1.1)

        metadata = dict(title="animation", artist="ignaciopineyro")
        writer = anime.PillowWriter(fps=15, metadata=metadata)

        xlist = []
        ylist = []

        with writer.saving(
            fig, f"{self.figures_directory_path}/{csv_file_name}_ivanimation.gif", 100
        ):
            for xval, yval in zip(df["vin"], -df["i(v1)"]):
                xlist.append(xval)
                ylist.append(yval)

                l.set_data(xlist, ylist)
                p1.set_data(xval, yval)
                writer.grab_frame()

        plt.close()

    def plot_networkx_graph(self):
        color_map = []
        labels = {}
        for node in self.graph.nx_graph:
            if node == self.graph.vin_minus:
                color_map.append("#f07b07")
                labels[node] = f"V- {node}"
            elif node == self.graph.vin_plus:
                color_map.append("#f07b07")
                labels[node] = f"V+ {node}"
            else:
                color_map.append("#93d9f5")
                labels[node] = node

        fig = plt.figure(figsize=(12, 8))
        try:
            average_shortest_path_length = nx.average_shortest_path_length(
                self.graph.nx_graph
            )
            average_clustering = nx.average_clustering(self.graph.nx_graph)
            title = (
                f"{self.graph.nx_graph.__str__()} V+={self.graph.vin_plus} V-={self.graph.vin_minus} "
                f"L={average_shortest_path_length:.2f} C={average_clustering:.2f} Seed={self.graph.seed}"
            )
        except NetworkXError:
            title = (
                f"{self.graph.nx_graph.__str__()} V+={self.graph.vin_plus} V-={self.graph.vin_minus} "
                f"Seed={self.graph.seed}"
            )
        plt.title(title)
        pos = nx.spring_layout(self.graph.nx_graph)
        nx.draw(
            self.graph.nx_graph,
            pos=pos,
            ax=fig.add_subplot(),
            with_labels=False,
            node_color=color_map,
            edge_color="#545454",
        )
        nx.draw_networkx_labels(
            self.graph.nx_graph,
            pos,
            labels,
            font_color="black",
            font_size=12,
            font_weight="bold",
        )
        fig.savefig(f"{self.figures_directory_path}/graph.jpg")
        plt.close()
