import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Sequence
from unittest import TestCase
from unittest.mock import patch

import action

MOCK_CONFIG = action.Config(
    application_name="demo-app",
    description="Test deploy",
    docker_compose_path=Path("docker/docker-compose.yml"),
    environment_name="demo-environment",
    platform_hooks_path=Path("platform-hooks"),
    region="eu-central-1",
    version_label="abc123456",
)
MOCK_APPLICATION = action.BeanstalkApplication(MOCK_CONFIG.application_name)
MOCK_ENVIRONMENT = action.BeanstalkEnvironment(MOCK_APPLICATION, MOCK_CONFIG.environment_name)
MOCK_APPLICATION_VERSION = action.ApplicationVersion(MOCK_APPLICATION, "version-0", "PROCESSED")
MOCK_TIME = datetime.now(tz=UTC)


class TestUtils(TestCase):
    def test_check_aws_credentials(self):
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "fake", "AWS_SECRET_ACCESS_KEY": "fake"}):
            action.check_aws_credentials()

        with self.assertRaises(ValueError):
            action.check_aws_credentials()

    def test_get_region(self):
        for variable in ("AWS_REGION", "AWS_DEFAULT_REGION"):
            with patch.dict(os.environ, {variable: "us-east-1"}):
                self.assertEqual(action.get_region(), "us-east-1")

        with self.assertRaises(ValueError):
            action.get_region()


class TestApplicationVersion(TestCase):
    def _get_or_create_application_version(self, polling_results: Sequence[Optional[action.ApplicationVersion]]):
        with NamedTemporaryFile() as docker_compose_file, patch.object(action, "boto3"), patch.object(
            action.ApplicationVersion,
            "get",
            side_effect=polling_results,
        ) as mock_get_application_version:
            result = action.get_or_create_beanstalk_application_version(
                MOCK_APPLICATION,
                replace(
                    MOCK_CONFIG,
                    docker_compose_path=Path(docker_compose_file.name),
                ),
                polling_interval=timedelta(0),
                polling_max_steps=len(polling_results) - 1,
            )
            self.assertEqual(mock_get_application_version.call_count, len(polling_results))
            return result

    def test_version_exists(self):
        with self.assertLogs() as captured:
            result = self._get_or_create_application_version((MOCK_APPLICATION_VERSION,))
            self.assertEqual(result, MOCK_APPLICATION_VERSION)
            self.assertEqual(
                captured.records[0].getMessage(),
                f"Application version {MOCK_CONFIG.version_label} already exist",
            )

    def test_create_new_version(self):
        result = self._get_or_create_application_version(
            (
                None,
                None,
                replace(MOCK_APPLICATION_VERSION, status="PROCESSING"),
                MOCK_APPLICATION_VERSION,
            ),
        )
        self.assertEqual(result, MOCK_APPLICATION_VERSION)

    def test_timeout_error(self):
        with self.assertRaises(TimeoutError):
            self._get_or_create_application_version((None,) * 5)


class TestDeployment(TestCase):
    def _deploy(self, get_health_return_values: Sequence[dict], is_active_in_environment: Sequence[bool]):
        with patch.object(
            action.BeanstalkEnvironment,
            "get_health",
            side_effect=get_health_return_values,
        ) as mock_get_health, patch.object(
            action.BeanstalkEnvironment,
            "get_events",
            return_value=(),
        ) as mock_get_events, patch.object(
            action.ApplicationVersion,
            "is_active_in_environment",
            side_effect=is_active_in_environment,
        ) as mock_is_active_in_environment, patch.object(
            action,
            "boto3",
        ):
            iterations = len(get_health_return_values)

            MOCK_APPLICATION_VERSION.deploy_to_environment(
                MOCK_ENVIRONMENT,
                polling_interval=timedelta(0),
                polling_max_steps=iterations,
            )

            self.assertEqual(mock_get_health.call_count, iterations)
            self.assertEqual(mock_get_events.call_count, iterations)
            mock_is_active_in_environment.assert_called_with(MOCK_ENVIRONMENT)
            self.assertEqual(mock_is_active_in_environment.call_count, len(is_active_in_environment))

    def test_successful_deployment(self):
        self._deploy(
            (
                {"Status": "InProgress", "Color": "Grey"},
                {"Status": "Ready", "Color": "Green"},
            ),
            (False, True),
        )

    def test_environment_timeout_error(self, *_):
        with self.assertRaises(TimeoutError):
            self._deploy(({"Status": "InProgress", "Color": "Grey"},) * 5, (False, True))

    def test_health_failed(self):
        with self.assertRaises(RuntimeError):
            self._deploy(({"Status": "Ready", "Color": "Red"},), (False, True))

    def test_version_not_active(self):
        with self.assertRaises(RuntimeError):
            self._deploy(({"Status": "Ready", "Color": "Green"},), (False, False))

    def test_version_already_active(self):
        version_label = MOCK_APPLICATION_VERSION.version_label
        with self.assertLogs() as captured:
            self._deploy((), (True,))
            self.assertEqual(
                captured.records[0].getMessage(),
                f"{version_label} already active in {MOCK_CONFIG.environment_name}, skip update!",
            )
