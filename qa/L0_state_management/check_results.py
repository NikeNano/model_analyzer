# Copyright (c) 2021, NVIDIA CORPORATION. All rights reserved.
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

from collections import defaultdict
import argparse
import yaml
import sys
import os
import re


class TestOutputValidator:
    """
    Functions that validate the output
    of the test
    """

    def __init__(self, config, test_name, checkpoint_dir, analyzer_log):
        self._config = config
        self._profile_models = list(config['profile_models'])
        self._analyzer_log = analyzer_log
        self._checkpoint_dir = checkpoint_dir

        check_function = self.__getattribute__(f'check_{test_name}')

        if check_function():
            sys.exit(0)
        else:
            sys.exit(1)

    def check_num_checkpoints(self):
        """
        Open the checkpoints directory and 
        check that there is 3 checkpoints
        """

        checkpoint_files = os.listdir(self._checkpoint_dir)
        return len(checkpoint_files) == len(self._profile_models)

    def check_loading_checkpoints(self):
        """
        Open the analyzer log and and make sure no perf
        analyzer runs took place
        """

        with open(self._analyzer_log, 'r') as f:
            log_contents = f.read()

        matches = re.findall('Profiling (\S+)', log_contents)
        for match in matches:
            # "Profiling server only metrics" is ok. No other "Profiling" lines should exist
            if match != "server":
                return False
        return True

    def check_interrupt_handling(self):
        """
        Open the checkpoints file and make sure there
        are only 3 checkpoints. Additionally
        check the analyzer log for a SIGINT.
        Also check that the 3rd model has
        been run once
        """

        checkpoint_files = os.listdir(self._checkpoint_dir)
        if len(checkpoint_files) != 2:
            return False

        with open(self._analyzer_log, 'r') as f:
            log_contents = f.read()

        # check for SIGINT
        token = "SIGINT"
        if log_contents.find(token) == -1:
            return False

        # check that 2nd model is profiled once
        token = f"Profiling {self._profile_models[1]}"
        token_idx = 0
        found_count = 0
        while True:
            token_idx = log_contents.find(token, token_idx + 1)
            if token_idx == -1:
                break
            found_count += 1

        return found_count == 1

    def check_early_exit(self):
        """
        Checks that no more than 1 model were profiled
        and that Triton server was stopped twice
        """

        with open(self._analyzer_log, 'r') as f:
            log_contents = f.read()

        if log_contents.find("Received SIGINT maximum number of times") == -1:
            print("\n***\n***  Early exit not triggered. \n***")
            return False
        elif log_contents.count("Profiling model") > 1:
            print("\n***\n***  Early exit not triggered on time. \n***")
            return False
        elif log_contents.count("Stopped Triton Server.") < 2:
            return False
        return True

    def check_continue_after_checkpoint(self,
                                        expected_resnet_count=3,
                                        expected_vgg_count=2):
        """
        Check that the 2nd model onwards have been run the correct
        number of times
        """

        profiled_models = self._profile_models[-2:]
        with open(self._analyzer_log, 'r') as f:
            log_contents = f.read()

        found_models_count = defaultdict(int)
        matches = re.findall('Profiling (\S+)', log_contents)
        for match in matches:
            base_model_name = match.rsplit('_', 2)[0]
            found_models_count[base_model_name] += 1

        # resnet50 libtorch normally has 4 runs:
        #   ([2 models, one of which is default] x [2 concurrencies])
        # but 1 was checkpointed from the previous interrupted run, so it
        # will do the remaining 3
        #
        # vgg19 will have 2 runs:
        #   ([2 models, one of which is default] x [1 concurrency])
        #
        expected_models_count = {}
        expected_models_count['resnet50_libtorch'] = expected_resnet_count
        expected_models_count['vgg19_libtorch'] = expected_vgg_count

        for i in range(2):
            model = profiled_models[i]
            if found_models_count[model] != expected_models_count[model]:
                return False
        return True

    def check_measurements_consistent_with_config(self):
        """
        Check that each of the last 2 models is profiled
        once, only the last 2 models appear in the results
        and that the first of the 2 profiled models appears
        twice in the result table
        """

        # Make sure models are run the correct number of times.
        # Normally resnet would be run 4 times. However, 2 were
        # already handled by the previous setup test, so it will
        # only execute twice.
        #
        if not self.check_continue_after_checkpoint(expected_resnet_count=2,
                                                    expected_vgg_count=2):
            return False

        profiled_models = self._profile_models[-2:]
        with open(self._analyzer_log, 'r') as f:
            log_contents = f.read()

        # Find table title and offset by token length and single newline character
        token = 'Models (Inference):'
        inference_table_start = log_contents.find(token)
        inference_table_start += len(token) + 1

        # Find gpu table title
        token = 'Models (GPU Metrics):'
        inference_table_end = log_contents.find(token)

        inference_table_contents = log_contents[
            inference_table_start:inference_table_end].strip()

        table_measurement_count = defaultdict(int)
        for line in inference_table_contents.split('\n'):
            model_name = line.split()[0]
            table_measurement_count[model_name] += 1

        # resnet50 libtorch has 4 results:
        #   ([2 models, one of which is default] x [2 concurrencies])
        # vgg19 will have 2 results:
        #   ([2 models, one of which is default] x [1 concurrency])
        #
        return table_measurement_count[profiled_models[
            0]] == 4 and table_measurement_count[profiled_models[1]] == 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f',
                        '--config-file',
                        type=str,
                        required=True,
                        help='The path to the config yaml file.')
    parser.add_argument('-d',
                        '--checkpoint-dir',
                        type=str,
                        required=True,
                        help='The checkpoint directory for the model analyzer.')
    parser.add_argument('-l',
                        '--analyzer-log-file',
                        type=str,
                        required=True,
                        help='The full path to the analyzer log.')
    parser.add_argument('-t',
                        '--test-name',
                        type=str,
                        required=True,
                        help='The name of the test to be run.')
    args = parser.parse_args()

    with open(args.config_file, 'r') as f:
        config = yaml.safe_load(f)

    TestOutputValidator(config, args.test_name, args.checkpoint_dir,
                        args.analyzer_log_file)
