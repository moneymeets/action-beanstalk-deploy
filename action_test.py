import hashlib
from unittest import TestCase
from unittest.mock import patch

import action
from action import ContainerConfig, ContainerMount, create_beanstalk_application_version, prepare_dockerrun_file


class MountsTest(TestCase):
    HOST_VOLUME_PATH = "/var/my-sample-application-test/data"
    HOST_VOLUME_NAME = hashlib.sha1(HOST_VOLUME_PATH.encode()).hexdigest()
    APP_NAME = "sample-application"
    IMAGE_NAME = "YourAwsAccountId.dkr.ecr.YourAwsRegion.amazonaws.com/your-ecr-repository"

    def _create_container_config(self, container_path: str):
        return ContainerConfig(
            dockerfile="docker/Dockerfile",
            name=self.APP_NAME,
            image_base_name=self.IMAGE_NAME,
            ports=(),
            mounts=(
                ContainerMount(
                    host_path=self.HOST_VOLUME_PATH,
                    container_path=container_path,
                    read_only=False,
                ),
            ),
        )

    def _create_dockerrun_config(self, app_version: str, *mounts: str):
        return {
            "AWSEBDockerrunVersion": 2,
            "volumes": [
                {
                    "name": self.HOST_VOLUME_NAME,
                    "host": {
                        "sourcePath": self.HOST_VOLUME_PATH,
                    },
                },
            ],
            "containerDefinitions": [
                {
                    "name": self.APP_NAME,
                    "image": f"{self.IMAGE_NAME}:{app_version}",
                    "environment": [],
                    "essential": True,
                    "links": [],
                    "memoryReservation": 1024,
                    "portMappings": [],
                    "mountPoints": [
                        {
                            "sourceVolume": self.HOST_VOLUME_NAME,
                            "containerPath": mount,
                            "readOnly": False,
                        },
                    ],
                }
                for mount in mounts
            ],
        }

    def _test_single_host_path(self, app_version: str, *container_mounts: str):
        containers = tuple(self._create_container_config(mount) for mount in container_mounts)

        self.assertDictEqual(
            prepare_dockerrun_file(containers, app_version),
            self._create_dockerrun_config(app_version, *container_mounts),
        )

    def test_single_mount_conversion(self):
        self._test_single_host_path("app-version", "/opt/data")

    def test_host_path_reuse(self):
        self._test_single_host_path("other-app-version", "/opt/data", "/opt/other-data")


@patch.object(action, "boto3")
class ApplicationVersionTest(TestCase):
    @patch.object(
        action,
        "get_application_versions",
        side_effect=[
            [],
            [{"Status": "PROCESSING"}],
            [{"Status": "PROCESSED"}],
        ],
    )
    def test_successful_response(self, mock_get_application_versions, *_):
        create_beanstalk_application_version(
            app="APP",
            version="abc12345",
            description="",
            bucket="bucket",
            archive="deploy-abc12345.zip",
        )
        self.assertEqual(mock_get_application_versions.call_count, 3)

    @patch.object(
        action,
        "get_application_versions",
        side_effect=[[{"Status": "PROCESSING"}] for i in range(4)],
    )
    def test_timeout_error(self, *_):
        with self.assertRaises(TimeoutError):
            create_beanstalk_application_version(
                app="APP",
                version="abc12345",
                description="",
                bucket="bucket",
                archive="deploy-abc12345.zip",
                max_retries=3,
                wait_time=0,
            )
