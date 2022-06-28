# Copyright (c) 2022, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .config_generator_interface import ConfigGeneratorInterface
from model_analyzer.config.run.run_config import RunConfig
from model_analyzer.model_analyzer_exceptions import TritonModelAnalyzerException
from model_analyzer.config.generate.model_run_config_generator import ModelRunConfigGenerator
from model_analyzer.config.generate.model_variant_name_manager import ModelVariantNameManager


class RunConfigGenerator(ConfigGeneratorInterface):
    """
    Generates all RunConfigs to execute given a list of models
    """

    def __init__(self, config, gpus, models, client):
        """
        Parameters
        ----------
        config: ModelAnalyzerConfig

        gpus: List of GPUDevices

        models: List of ConfigModelProfileSpec
            The models to generate ModelRunConfigs for

        client: TritonClient
        """
        self._config = config
        self._gpus = gpus
        self._models = models
        self._client = client

        self._triton_env = RunConfigGenerator.determine_triton_server_env(
            models)

        self._num_models = len(models)

        self._curr_model_run_configs = [None for n in range(self._num_models)]
        self._curr_results = [[] for n in range(self._num_models)]
        self._curr_generators = [None for n in range(self._num_models)]
        self._default_returned = False

        self._model_variant_name_manager = ModelVariantNameManager()

    def set_last_results(self, measurements):
        for index in range(self._num_models):
            self._curr_results[index].extend(measurements)

    def get_configs(self):
        """
        Returns
        -------
        RunConfig
            The next RunConfig generated by this class
        """

        yield from self._get_next_config()

    def _get_next_config(self):
        yield from self._generate_subset(0, default_only=True)
        self._default_returned = True
        yield from self._generate_subset(0, default_only=False)

    def _generate_subset(self, index, default_only):
        mrcg = ModelRunConfigGenerator(self._config, self._gpus,
                                       self._models[index], self._client,
                                       self._model_variant_name_manager,
                                       default_only)

        self._curr_generators[index] = mrcg

        for model_run_config in mrcg.get_configs():
            self._curr_model_run_configs[index] = model_run_config

            if index == (len(self._models) - 1):
                yield (self._make_run_config())
            else:
                yield from self._generate_subset(index + 1, default_only)

            self._send_results_to_generator(index)

    def _make_run_config(self):
        run_config = RunConfig(self._triton_env)
        for index in range(len(self._models)):
            run_config.add_model_run_config(self._curr_model_run_configs[index])
        return run_config

    def _send_results_to_generator(self, index):
        self._curr_generators[index].set_last_results(self._curr_results[index])
        self._curr_results[index] = []

    @classmethod
    def determine_triton_server_env(cls, models):
        """
        Given a list of models, return the triton environment
        """
        triton_env = models[0].triton_server_environment()

        for model in models:
            if model.triton_server_environment() != triton_env:
                raise TritonModelAnalyzerException(
                    f"Mismatching triton server environments. The triton server environment must be the same for all models when run concurrently"
                )

        return triton_env
