import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

import boto3
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass(frozen=True)
class Config:
    application_name: str
    description: str
    docker_compose_path: Path
    environment_name: str
    platform_hooks_path: Optional[Path]
    region: str
    version_label: str

    @property
    def application_version_bucket_key(self):
        return f"{self.application_name}/{self.version_label}.zip"

    @property
    def application_version_bucket_name(self):
        return f"elasticbeanstalk-{self.region}-{boto3.client('sts').get_caller_identity().get('Account')}"


@dataclass(frozen=True)
class BeanstalkApplication:
    name: str


@dataclass(frozen=True)
class BeanstalkEnvironment:
    application: BeanstalkApplication
    name: str

    def get_health(self) -> dict:
        return boto3.client("elasticbeanstalk").describe_environment_health(
            EnvironmentName=self.name,
            AttributeNames=["HealthStatus", "InstancesHealth", "Causes", "Color", "Status"],
        )

    def get_events(self, last_event_time: datetime) -> Sequence[dict]:
        return tuple(
            reversed(
                boto3.client("elasticbeanstalk").describe_events(
                    ApplicationName=self.application.name,
                    EnvironmentName=self.name,
                    StartTime=last_event_time,
                )["Events"],
            ),
        )

    def wait_for_update_is_ready_and_get_health(
        self,
        start_time: datetime,
        polling_max_steps: int,
        polling_interval: timedelta,
    ) -> dict:
        step = 0
        last_event_time = start_time
        while step < polling_max_steps:
            events = self.get_events(last_event_time)
            health = self.get_health()

            logging.info(f"Step {step + 1} of {polling_max_steps}. Status is {health['Status']}")

            # Log all events in order they occur beginning at the last event time
            for event in events:
                logging.info(event["Message"])
                last_event_time = event["EventDate"]

            if health["Status"] == "Ready":
                return health

            time.sleep(polling_interval.total_seconds())
            step += 1

        raise TimeoutError("Deployment not finished until timeout")


@dataclass(frozen=True)
class DeploymentArchive:
    version_label: str
    bucket_name: str
    bucket_key: str

    @classmethod
    def create(
        cls,
        docker_compose_path: Path,
        platform_hooks_path: Optional[Path],
        version_label: str,
        bucket_name: str,
        bucket_key: str,
    ) -> "DeploymentArchive":
        def create_zip() -> bytes:
            output_data = BytesIO()
            with ZipFile(output_data, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(
                    "docker-compose.yml",
                    docker_compose_path.read_text().replace("${IMAGE_TAG}", version_label),
                )
                if platform_hooks_path is not None:
                    for file in filter(lambda path: path.is_file(), platform_hooks_path.glob("**/*")):
                        archive.write(file, arcname=file.relative_to(platform_hooks_path))

            logging.info("Deployment archive created")
            output_data.seek(0)
            return output_data.getvalue()

        def upload_zip(content: bytes) -> DeploymentArchive:
            boto3.client("s3").put_object(Bucket=bucket_name, Body=content, Key=bucket_key)
            logging.info(f"Deployment archive uploaded to s3://{bucket_name}/{bucket_key}")
            return DeploymentArchive(version_label=version_label, bucket_name=bucket_name, bucket_key=bucket_key)

        return upload_zip(create_zip())


@dataclass(frozen=True)
class ApplicationVersion:
    application: BeanstalkApplication
    version_label: str
    status: str

    @classmethod
    def get(cls, application: BeanstalkApplication, version_label: str) -> Optional["ApplicationVersion"]:
        versions = boto3.client("elasticbeanstalk").describe_application_versions(
            ApplicationName=application.name,
            VersionLabels=[version_label],
            MaxRecords=1,
        )["ApplicationVersions"]

        if not versions:
            return None

        (version,) = versions
        return ApplicationVersion(
            application=BeanstalkApplication(version["ApplicationName"]),
            version_label=version["VersionLabel"],
            status=version["Status"],
        )

    @classmethod
    def create(
        cls,
        application: BeanstalkApplication,
        description: str,
        deployment_archive: DeploymentArchive,
        polling_max_steps: int,
        polling_interval: timedelta,
    ):
        version_label = deployment_archive.version_label

        boto3.client("elasticbeanstalk").create_application_version(
            ApplicationName=application.name,
            VersionLabel=version_label,
            Description=description,
            SourceBundle={
                "S3Bucket": deployment_archive.bucket_name,
                "S3Key": deployment_archive.bucket_key,
            },
            Process=True,
        )

        logging.info("Beanstalk application version created")

        def wait_until_created():
            step = 0
            while step < polling_max_steps:
                application_version = cls.get(application, version_label)
                status = "UNAVAILABLE" if application_version is None else application_version.status

                logging.info(f"Step {step + 1} of {polling_max_steps}. Status is {status}")
                if status == "PROCESSED":
                    return application_version

                time.sleep(polling_interval.total_seconds())
                step += 1

            raise TimeoutError("Application Version creation not finished until timeout")

        return wait_until_created()

    def is_active_in_environment(self, environment: BeanstalkEnvironment) -> bool:
        return bool(
            boto3.client("elasticbeanstalk").describe_environments(
                ApplicationName=self.application.name,
                VersionLabel=self.version_label,
                EnvironmentNames=[environment.name],
            )["Environments"],
        )

    def deploy_to_environment(
        self,
        environment: BeanstalkEnvironment,
        polling_max_steps: int = 150,
        polling_interval: timedelta = timedelta(seconds=8),
    ):
        assert environment.application == self.application

        if self.is_active_in_environment(environment):
            logging.info(f"{self.version_label} already active in {environment.name}, skip update!")
            return

        boto3.client("elasticbeanstalk").update_environment(
            ApplicationName=self.application.name,
            EnvironmentName=environment.name,
            VersionLabel=self.version_label,
        )

        start_time = datetime.utcnow()
        health = environment.wait_for_update_is_ready_and_get_health(
            start_time,
            polling_max_steps=polling_max_steps,
            polling_interval=polling_interval,
        )

        if health["Color"] != "Green" or not self.is_active_in_environment(environment):
            logging.warning(json.dumps(health, indent=4))
            raise RuntimeError(f"Deployment of '{self}' to '{environment}' failed!")


def get_or_create_beanstalk_application_version(
    application: BeanstalkApplication,
    config: Config,
    polling_max_steps: int = 20,
    polling_interval: timedelta = timedelta(seconds=1),
) -> ApplicationVersion:
    version_label = config.version_label

    application_version = ApplicationVersion.get(application, version_label)

    if application_version is not None:
        logging.info(f"Application version {version_label} already exist")
        return application_version

    return ApplicationVersion.create(
        application=application,
        description=config.description,
        deployment_archive=DeploymentArchive.create(
            docker_compose_path=config.docker_compose_path,
            platform_hooks_path=config.platform_hooks_path,
            version_label=version_label,
            bucket_name=config.application_version_bucket_name,
            bucket_key=config.application_version_bucket_key,
        ),
        polling_max_steps=polling_max_steps,
        polling_interval=polling_interval,
    )


def check_aws_credentials():
    aws_credential_variables = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    if not all(variable in os.environ for variable in aws_credential_variables):
        raise ValueError(f"AWS credentials not configured ({', '.join(aws_credential_variables)})")


def get_region() -> str:
    region_variables = ("AWS_REGION", "AWS_DEFAULT_REGION")
    for region_var in region_variables:
        if region := os.environ.get(region_var):
            return region

    raise ValueError(f"AWS region not configured, set one of ({', '.join(region_variables)})")


def main():
    check_aws_credentials()
    config = Config(
        application_name=os.environ["APPLICATION_NAME"],
        description=os.environ["VERSION_DESCRIPTION"],
        docker_compose_path=Path(os.environ["DOCKER_COMPOSE_PATH"]),
        environment_name=os.environ["ENVIRONMENT_NAME"],
        platform_hooks_path=Path(os.environ["PLATFORM_HOOKS_PATH"]) if os.environ["PLATFORM_HOOKS_PATH"] else None,
        region=get_region(),
        version_label=os.environ["VERSION_LABEL"],
    )

    application = BeanstalkApplication(config.application_name)
    environment = BeanstalkEnvironment(application, config.environment_name)

    application_version = get_or_create_beanstalk_application_version(application, config)

    application_version.deploy_to_environment(environment)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    logger = logging.getLogger(__file__)

    main()
