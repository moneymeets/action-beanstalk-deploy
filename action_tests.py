from unittest import TestCase

from action import ContainerConfig, ContainerMount, prepare_dockerrun_file


class MountsTest(TestCase):
    @staticmethod
    def _create_container_config(host_path: str, container_path: str):
        return ContainerConfig(
            dockerfile="docker/Dockerfile",
            name="sample-application",
            image_base_name="YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository",
            ports=(),
            mounts=(
                ContainerMount(
                    host_path=host_path,
                    container_path=container_path,
                    read_only=False,
                ),
            ),
        )

    def test_single_mount_conversion(self):
        containers = (
            self._create_container_config("/var/my-sample-application-test/data", "/opt/data"),
        )

        file = prepare_dockerrun_file(containers, "app-version")

        self.assertDictEqual(
            file,
            {
                "AWSEBDockerrunVersion": 2,
                "volumes": [
                    {
                        "name": "d70bd7c66adfa8babb6f5fa151d41d431fc121ff",
                        "host": {
                            "sourcePath": "/var/my-sample-application-test/data",
                        },
                    },
                ],
                "containerDefinitions": [
                    {
                        "name": "sample-application",
                        "image": "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository:app-version",
                        "environment": [],
                        "essential": True,
                        "links": (),
                        "memoryReservation": 1024,
                        "portMappings": [],
                        "mountPoints": [
                            {
                                "sourceVolume": "d70bd7c66adfa8babb6f5fa151d41d431fc121ff",
                                "containerPath": "/opt/data",
                                "readOnly": False,
                            },
                        ],
                    },
                ],
            },
        )

    def test_non_unique_host_paths(self):
        containers = (
            self._create_container_config("/var/my-sample-application-test/data", "/opt/data"),
            self._create_container_config("/var/my-sample-application-test/data", "/opt/other-data"),
        )

        file = prepare_dockerrun_file(containers, "app-version")

        self.assertDictEqual(
            file,
            {
                "AWSEBDockerrunVersion": 2,
                "volumes": [
                    {
                        "name": "d70bd7c66adfa8babb6f5fa151d41d431fc121ff",
                        "host": {
                            "sourcePath": "/var/my-sample-application-test/data",
                        },
                    },
                ],
                "containerDefinitions": [
                    {
                        "name": "sample-application",
                        "image": "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository:app-version",
                        "environment": [],
                        "essential": True,
                        "links": (),
                        "memoryReservation": 1024,
                        "portMappings": [],
                        "mountPoints": [
                            {
                                "sourceVolume": "d70bd7c66adfa8babb6f5fa151d41d431fc121ff",
                                "containerPath": "/opt/data",
                                "readOnly": False,
                            },
                        ],
                    },
                    {
                        "name": "sample-application",
                        "image": "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository:app-version",
                        "environment": [],
                        "essential": True,
                        "links": (),
                        "memoryReservation": 1024,
                        "portMappings": [],
                        "mountPoints": [
                            {
                                "sourceVolume": "d70bd7c66adfa8babb6f5fa151d41d431fc121ff",
                                "containerPath": "/opt/other-data",
                                "readOnly": False,
                            },
                        ],
                    },
                ],
            },
        )
