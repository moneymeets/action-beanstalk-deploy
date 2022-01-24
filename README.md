# action-beanstalk-deploy

GitHub action for AWS Elastic Beanstalk deployment

# Introduction

This action creates or reuses a Beanstalk application version and triggers the environment update.

## Prerequisites

* existing docker image in your docker registry
* docker-compose.yml with `${IMAGE_TAG}` variable as tag
* optional: directory with custom platform hooks

## Platform hooks

You can provide custom platform hooks, by specifying the `platform_hooks_path` key.
Example of the directory structure:

```
.ebextensions/
    config.config
.platform/
    hooks/
      prebuild/
        mount.sh
    ...
```

For more detailed information about platform hooks, see: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/platforms-linux-extend.html

# Usage

See [action.yml](action.yml).

Basic (with default values):

```yaml
steps:
  - name: Deploy
    uses: moneymeets/action-beanstalk-deploy@master
    with:
      application_name: demo-app
      environment_name: "${{ format('demo-app-{0}', github.event.deployment.environment) }}"
      platform_hooks_path: "${{ github.workspace }}/beanstalk-platform-hooks"
      region: eu-central-1
```

With full list of parameters:

```yaml
steps:
  - name: Deploy
    uses: moneymeets/action-beanstalk-deploy@master
    with:
      application_name: demo-app
      docker_compose_path: "${{ github.workspace }}/docker/docker-compose.yml"
      environment_name: "${{ format('demo-app-{0}', github.event.deployment.environment) }}"
      platform_hooks_path: "${{ github.workspace }}/beanstalk-platform-hooks"
      region: eu-central-1
      version_label: ${{ github.sha }}
      version_description: "GitHub Action #${{ github.run_number }}"

```

# Local testing
Make sure that valid AWS credentials are exported into your profile, or located in `~/.aws/credentials` file.

```bash
export APPLICATION_NAME=demo-app
export ENVIRONMENT_NAME=demo-app-dev
export PLATFORM_HOOKS_PATH=beanstalk-platform-hooks
export REGION=eu-central-1
export VERSION_LABEL=SampleVersionLabel
export VERSION_DESCRIPTION=SampleVersionDescription
export DOCKER_COMPOSE_PATH=docker/docker-compose.yml
export PYTHONUNBUFFERED="1"

poetry run python action.py
```
