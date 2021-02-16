#!/usr/bin/env python3

import json
import logging
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import boto3
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass(frozen=True)
class PortMapping:
    host: int
    container: int


@dataclass_json
@dataclass(frozen=True)
class ContainerConfig:
    name: str
    dockerfile: str
    image_base_name: str
    ports: tuple[PortMapping, ...]
    memory: int = 1024
    links: tuple[str, ...] = ()

    def get_image_url(self, version):
        return f"{self.image_base_name}:{version}"


@dataclass_json
@dataclass(frozen=True)
class ConfigFromEnv:
    version_label: str
    version_description: str
    wait_for_deployment: bool
    base_path: str

    @property
    def deployment_archive(self):
        return f"deploy-{self.version_label}.zip"


@dataclass_json
@dataclass(frozen=True)
class ConfigFromFile:
    build_and_upload_image: bool
    application_name: str
    environment_name: str
    application_version_bucket: str
    containers: tuple[ContainerConfig, ...]


def run_commands(commands: tuple[str, ...]):
    for command in commands:
        run_command(command)


def run_command(command: str):
    logging.info(command)
    subprocess.run(command, check=True, shell=True)


def prepare_dockerrun_file(containers: tuple[ContainerConfig, ...], version: str) -> dict[str, ...]:
    return {
        "AWSEBDockerrunVersion": 2,
        "volumes": [],
        "containerDefinitions": [
            {
                "name": container.name,
                "image": container.get_image_url(version),
                "environment": [],
                "essential": True,
                "links": container.links,
                "memoryReservation": container.memory,
                "portMappings": [
                    {
                        "hostPort": port.host,
                        "containerPort": port.container,
                    }
                    for port in container.ports
                ],

            }
            for container in containers
        ],
    }


def create_deployment_archive(output_file: Path, config: tuple[ContainerConfig, ...], version_label: str):
    with ZipFile(output_file, "w") as archive:
        data = json.dumps(prepare_dockerrun_file(config, version_label), indent=4)
        archive.writestr("Dockerrun.aws.json", data, compress_type=ZIP_DEFLATED)


def upload_deployment_archive_to_s3(application_version_bucket: str, deployment_archive: Path):
    boto3.client("s3").put_object(
        Bucket=application_version_bucket,
        Body=deployment_archive.read_bytes(),
        Key=deployment_archive.name,
    )


def create_and_upload_deployment_archive(
        deployment_archive: str,
        containers: tuple[ContainerConfig, ...],
        version_label: str,
        application_version_bucket: str,
):
    output_path = Path(".build-artifacts")
    output_path.mkdir(exist_ok=True)
    output_file = output_path / deployment_archive

    create_deployment_archive(
        output_file=output_file,
        config=containers,
        version_label=version_label,
    )

    upload_deployment_archive_to_s3(application_version_bucket, output_file)


def build_image(containers: ContainerConfig, dockerfile: Path, build_path: Path):
    run_command(f"docker build -t {containers.name}-ci -f {build_path / dockerfile} {build_path}")


def upload_image_to_ecr(containers: ContainerConfig, version_label: str):
    image_destination = containers.get_image_url(version_label)
    run_commands(
        (
            f"docker tag {containers.name}-ci {image_destination}",
            "$(aws ecr get-login --no-include-email)",
            f"docker push {image_destination}",
        ),
    )


def build_and_upload_images(containers: tuple[ContainerConfig, ...], base_path: str, version_label: str):
    for container in containers:
        build_image(container, Path(container.dockerfile), Path(base_path))
        upload_image_to_ecr(container, version_label)


def create_beanstalk_application_version(app: str, version: str, description: str, bucket: str, archive: str):
    boto3.client("elasticbeanstalk").create_application_version(
        ApplicationName=app,
        VersionLabel=version,
        Description=description,
        SourceBundle={
            "S3Bucket": bucket,
            "S3Key": archive,
        },
        Process=True,
    )


def get_deployment_status(environment_name: str) -> dict[str, ...]:
    return boto3.client("elasticbeanstalk").describe_environment_health(
        EnvironmentName=environment_name,
        AttributeNames=[
            "HealthStatus",
            "InstancesHealth",
            "Causes",
            "Color",
            "Status",
        ],
    )


def is_version_deployed(environment_name: str, version: str, application_name: str) -> bool:
    return bool(boto3.client("elasticbeanstalk").describe_environments(
        ApplicationName=application_name,
        VersionLabel=version,
        EnvironmentNames=[environment_name],
    )["Environments"])


def wait_until_deployment_successful_finished(
        application_name: str,
        environment_name: str,
        version_label: str,
        wait_timeout: int = 20 * 60,
        wait_time_step: int = 8,
):
    def wait_for_update_is_ready(timeout: int, wait_time: int):
        steps = int(math.ceil(timeout / wait_time))
        for step in range(steps):
            deployment_status = get_deployment_status(environment_name)

            logging.info(f"Step {step} of {steps}. Status is {deployment_status['Status']}")
            if deployment_status["Status"] == "Ready":
                return deployment_status

            time.sleep(wait_time)

        raise TimeoutError("Deployment not finished until timeout")

    status = wait_for_update_is_ready(wait_timeout, wait_time_step)

    if status["Color"] != "Green":
        logging.warning(json.dumps(status, indent=4))
        raise RuntimeError(f"Deployment of '{version_label}' failed!")

    if not is_version_deployed(environment_name, version_label, application_name):
        raise RuntimeError(f"Deployment of '{version_label}' to '{environment_name}' failed!")

    logging.info("Deployment successful")


def update_beanstalk_environment(application_name: str, environment_name: str, version_label: str):
    boto3.client("elasticbeanstalk").update_environment(
        ApplicationName=application_name,
        EnvironmentName=environment_name,
        VersionLabel=version_label,
    )


def prepare_config() -> tuple[ConfigFromEnv, ConfigFromFile]:
    def check_bool(value: str) -> bool:
        return False if value in ("", "0", "False", "false") else True

    return ConfigFromEnv(
        version_label=os.environ["VERSION_LABEL"],
        version_description=os.environ["VERSION_DESCRIPTION"],
        wait_for_deployment=check_bool(os.environ["WAIT_FOR_DEPLOYMENT"]),
        base_path=os.environ["BASE_PATH"],
    ), ConfigFromFile.from_json(Path(os.environ["CONFIG_PATH"]).read_bytes())


def main(config: tuple[ConfigFromEnv, ConfigFromFile]):
    config_from_env, config_from_file = config

    if config_from_file.build_and_upload_image:
        build_and_upload_images(
            containers=config_from_file.containers,
            base_path=config_from_env.base_path,
            version_label=config_from_env.version_label,
        )

    create_and_upload_deployment_archive(
        deployment_archive=config_from_env.deployment_archive,
        containers=config_from_file.containers,
        version_label=config_from_env.version_label,
        application_version_bucket=config_from_file.application_version_bucket,
    )

    create_beanstalk_application_version(
        app=config_from_file.application_name,
        version=config_from_env.version_label,
        description=config_from_env.version_description,
        bucket=config_from_file.application_version_bucket,
        archive=config_from_env.deployment_archive,
    )

    update_beanstalk_environment(
        application_name=config_from_file.application_name,
        environment_name=config_from_file.environment_name,
        version_label=config_from_env.version_label,
    )

    wait_until_deployment_successful_finished(
        application_name=config_from_file.application_name,
        environment_name=config_from_file.environment_name,
        version_label=config_from_env.version_label,
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    logger = logging.getLogger(__file__)

    main(config=prepare_config())
